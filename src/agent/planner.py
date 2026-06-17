"""Planner: orchestrates the LLM → tool-call → result agentic loop.

Flow for each user request:
  1. Build an initial messages list (system + user turn).
  2. Call the LLM.  If it requests tool calls, execute them against the engine
     and feed the results back as the next user turn.
  3. Repeat until the LLM produces a final text answer or the iteration cap
     is reached.
  4. Return the final answer string to main.py.

Hallucinated tool names are caught gracefully: an error message is returned
as the tool result so the LLM can recover without crashing the process.
"""

import json
import logging
import os
import re
import sys
from typing import Any, Callable, Dict, List

from utils.config import Config
from eda_engine.engine import EDAEngine
from agent.llm_client import LLMClient, ToolCall
from agent.tool_spec import EDA_TOOLS

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 10   # max LLM round-trips per user request

_SYSTEM_PROMPT = (
    "You are an AI agent for an Electronic Design Automation (EDA) system. "
    "Your job is to help users analyse and transform gate-level Verilog netlists. "
    "Use the provided tools to load designs, perform analysis, and write results. "
    "Designs are located in the 'testcase/<case_name>/' directory "
    "(e.g., testcase/test01/test01.v). "
    "When writing or saving a design, ALWAYS save the output file to the same "
    "testcase directory (e.g., testcase/test01/test01_out.v). "
    "After receiving tool outputs, synthesise a clear, concise technical answer "
    "for the user. IMPORTANT: Always use the exact numerical values, counts, "
    "and lists provided directly by the tool outputs. Do not attempt to "
    "re-count items or recalculate values from text lists yourself. "
    "When a tool result contains a 'saved_to_file' field, it means "
    "the full output was too large to fit in context and has been saved to "
    "that file. You MUST mention the file path in your response so the user "
    "knows where to find the complete data. Always report the total count and "
    "include the sample items from the result. "
    "When a decompose/replace tool result contains 'gate_delta', use those "
    "exact numbers to report how many gates were added and removed. "
    "Whenever a request asks you to transform the design while preserving "
    "functionality (e.g. 'make sure nothing changes functionally', 'ensure "
    "functional equivalence'), call check_equivalence after the transformation "
    "to formally verify the result before writing the design, and report the outcome. "
    "Do not discuss scoring, judging, or the evaluation process."
)


class Planner:
    """Drives the LLM tool-calling loop and executes tool calls on the EDA engine."""

    def __init__(self, config: Config, engine: EDAEngine) -> None:
        self._engine = engine
        self._llm = LLMClient(config, EDA_TOOLS)

        # Map every tool name to the corresponding engine method.
        # Extend this dict when new tools are added to tool_spec.py.
        self._dispatch: Dict[str, Callable[..., str]] = {
            "load_design":   engine.load_design,
            "write_design":  engine.write_design,
            "analyze_depth": engine.analyze_depth,
            "analyze_critical_path": engine.analyze_critical_path,
            "find_paths":    engine.find_paths,
            "get_node_info": engine.get_node_info,
            "list_nodes":    engine.list_nodes,
            "replace_gate":  engine.replace_gate,
            "count_gates":   engine.count_gates,
            "count_fanin_gates": engine.count_fanin_gates,
            "insert_buffers": engine.insert_buffers,
            "reduce_depth": engine.reduce_depth,
            "remove_dangling": engine.remove_dangling,
            "rename_node": engine.rename_node,
            "decompose_gates_in_cone": engine.decompose_gates_in_cone,
            "collapse_inverters": engine.collapse_inverters,
            "merge_equivalent_gates": engine.merge_equivalent_gates,
            "convert_cone_to_basis": engine.convert_cone_to_basis,
            "reconstruct_netlist_to_basis": engine.reconstruct_netlist_to_basis,
            "restructure_to_depth": engine.restructure_to_depth,
            "optimize_outputs_to_depth": engine.optimize_outputs_to_depth,
            "check_equivalence": engine.check_equivalence,
            "count_fanout_gates": engine.count_fanout_gates,
            "get_fanin_cone": engine.get_fanin_cone,
            "get_fanout_cone": engine.get_fanout_cone,
            "get_fanin_depth": engine.get_fanin_depth,
        }

    # ------------------------------------------------------------------ public

    def reset(self) -> None:
        """Clear EDA engine state for a new testcase."""
        self._engine.reset()

    def _build_system_prompt(self) -> str:
        """Include live EDA engine state so follow-up requests see loaded designs."""
        if self._engine.is_design_loaded:
            state = (
                f"A design is already loaded from '{self._engine.loaded_filepath}'. "
                "Do not reload unless the user asks for a different file; "
                "use analysis and write tools on the current design."
            )
        else:
            state = "No design is currently loaded."
        return f"{_SYSTEM_PROMPT}\n\nCurrent session state: {state}"

    def process(self, user_request: str) -> str:
        """Process one natural-language request and return the response text.

        Args:
            user_request: A single line from stdin (already stripped).

        Returns:
            A plain-text response suitable for wrapping in #RESPONSE/#END tags.
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user",   "content": user_request},
        ]

        for iteration in range(_MAX_ITERATIONS):
            try:
                response = self._llm.chat(messages)
            except Exception as exc:
                logger.error("LLM API error (iteration %d): %s", iteration, exc)
                return f"Error communicating with the LLM service: {exc}"

            if response.tool_calls:
                # Append the assistant's tool-request turn to history.
                messages.append(response.raw_message)

                # Execute every requested tool and append the results.
                for tc in response.tool_calls:
                    result = self._execute_tool(tc)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )

            elif response.text is not None:
                return response.text.strip() or "(No response generated.)"

            else:
                # Unexpected state: no text and no tool calls.
                logger.warning("LLM returned empty response on iteration %d", iteration)
                break

        return (
            "I was unable to complete the request within the allowed number of steps."
        )

    # ----------------------------------------------------------------- private

    def _execute_tool(self, tc: ToolCall) -> str:
        """Dispatch *tc* to the matching engine method and return a result string.

        Returns an informative error string on unknown or malformed tool calls
        so the LLM receives feedback and can attempt recovery.

        Large results are automatically truncated and saved to a file so they
        do not blow up the LLM context window.
        """
        fn = self._dispatch.get(tc.name)
        if fn is None:
            known = list(self._dispatch.keys())
            return (
                f"Error: unknown tool '{tc.name}'. "
                f"Available tools: {known}. "
                f"Please call one of the listed tools."
            )

        try:
            result = fn(**tc.arguments)
            result = str(result)
            # ── Tool Interceptor: truncate oversized results ──────────
            result = self._truncate_large_result(result, tc.name, tc.arguments)
            return result
        except TypeError as exc:
            # Wrong argument names — the LLM hallucinated a parameter.
            return (
                f"Error: tool '{tc.name}' was called with invalid arguments "
                f"{tc.arguments}: {exc}"
            )
        except Exception as exc:
            logger.error("Tool '%s' raised an exception: %s", tc.name, exc)
            return f"Error executing '{tc.name}': {exc}"

    # ── Token-size threshold (roughly 4 chars per token) ──────────────────
    _MAX_RESULT_CHARS = 12000  # ~3000 tokens — safe for any provider

    def _truncate_large_result(
        self, result: str, tool_name: str, arguments: Dict[str, Any]
    ) -> str:
        """If *result* exceeds the character budget, save it to a log file
        and return a compact JSON summary instead.

        This is a generic interceptor that protects against ANY tool returning
        a massive string (list_nodes, get_fanin_cone, get_fanout_cone, etc.).
        The find_paths tool has its own built-in truncation in engine.py, so
        results that are already JSON-formatted are passed through.
        """
        # Skip results that are already compact JSON (e.g. from find_paths).
        if result.lstrip().startswith("{"):
            return result

        if len(result) <= self._MAX_RESULT_CHARS:
            return result

        # ── Derive a save path ────────────────────────────────────────────
        save_dir = None
        if self._engine.loaded_filepath:
            save_dir = os.path.dirname(self._engine.loaded_filepath)

        # Build a descriptive filename from the tool name and arguments.
        arg_tag = "_".join(str(v) for v in arguments.values()) if arguments else ""
        arg_tag = re.sub(r"[\[\]/\\\s]", "_", arg_tag)[:60]
        filename = f"{tool_name}_{arg_tag}.log" if arg_tag else f"{tool_name}.log"
        log_path = os.path.join(save_dir, filename) if save_dir else filename

        with open(log_path, "w", encoding="utf-8") as f:
            f.write(result)

        # ── Build a compact summary ───────────────────────────────────────
        lines = result.splitlines()
        total_lines = len(lines)
        samples = lines[:5]

        summary = {
            "notice": (
                f"The output from '{tool_name}' is too large to fit in LLM context "
                f"({total_lines} lines). Full details saved to {log_path}"
            ),
            "total_lines": total_lines,
            "saved_to_file": log_path,
            "samples": samples,
        }
        return json.dumps(summary, ensure_ascii=False, indent=2)

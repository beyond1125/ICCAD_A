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

    "ANALYSIS tools: count_gates, list_nodes, get_node_info, get_fanin_cone, get_fanout_cone, count_fanin_gates, count_fanout_gates, get_fanin_depth, analyze_depth, analyze_critical_path, find_paths, list_pio (PI/PO listing with bit widths — zero params), deepest_cone_output (which output has deepest fanin cone — zero params), r2r_paths (list all register-to-register paths through combinational logic — zero params)."
    "TRANSFORM tools: replace_gate (single gate type change), insert_buffers (fanout-based), insert_dedicated_buffers (per-signal), reduce_depth (ABC optimization), remove_dangling, rename_node, decompose_gates_in_cone (cone-scoped decomposition), collapse_inverters (remove back-to-back NOT pairs — zero params, just call it), merge_equivalent_gates (remove structural duplicates — zero params), convert_cone_to_basis (cone to target basis), reconstruct_netlist_to_basis (ENTIRE design to target basis), restructure_to_depth, optimize_outputs_to_depth, const_propagate (simplify gates with constant inputs; mode='report' to scan, 'propagate' to simplify with cascading; optional gate_type and const_value filters)."
    "IO tools: load_design, write_design."
    "VERIFY tools: check_equivalence."

    "KEY RULES:"
    " For 'collapse/remove back-to-back inverters': use collapse_inverters directly."
    " For 'replace ALL gates of type X in the ENTIRE design': use reconstruct_netlist_to_basis if converting to a basis, or iterate replace_gate."
    " For 'replace gates of type X WITHIN a cone': use decompose_gates_in_cone or convert_cone_to_basis."
    " For gate counts after transformation: read gate_delta from the tool result, do NOT recount manually."
    " For 'how many PI/PO', 'list all primary inputs/outputs': use list_pio directly."
    " For 'which output has deepest cone', 'max combinational depth': use deepest_cone_output directly."
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
            "list_gates_by_type": engine.list_gates_by_type,
            "flipflops_by_clock": engine.flipflops_by_clock,
            "max_pi_to_dff_depth": engine.max_pi_to_dff_depth,
            "list_floating": engine.list_floating,
            "signal_depends_on": engine.signal_depends_on,
            "highest_fanout_pi": engine.highest_fanout_pi,
            "list_nodes":    engine.list_nodes,
            "replace_gate":  engine.replace_gate,
            "count_gates":   engine.count_gates,
            "count_fanin_gates": engine.count_fanin_gates,
            "insert_buffers": engine.insert_buffers,
            "insert_dedicated_buffers": engine.insert_dedicated_buffers,
            "buffer_signal": engine.buffer_signal,
            "reconnect_pin": engine.reconnect_pin,
            "reduce_depth": engine.reduce_depth,
            "remove_dangling": engine.remove_dangling,
            "rename_node": engine.rename_node,
            "decompose_gates_in_cone": engine.decompose_gates_in_cone,
            "decompose_all_gates": engine.decompose_all_gates,
            "collapse_inverters": engine.collapse_inverters,
            "merge_equivalent_gates": engine.merge_equivalent_gates,
            "convert_cone_to_basis": engine.convert_cone_to_basis,
            "reconstruct_netlist_to_basis": engine.reconstruct_netlist_to_basis,
            "restructure_to_depth": engine.restructure_to_depth,
            "optimize_outputs_to_depth": engine.optimize_outputs_to_depth,
            "const_propagate": engine.const_propagate,
            "check_equivalence": engine.check_equivalence,
            "count_fanout_gates": engine.count_fanout_gates,
            "get_fanin_cone": engine.get_fanin_cone,
            "get_fanout_cone": engine.get_fanout_cone,
            "get_fanin_depth": engine.get_fanin_depth,
            "r2r_paths": engine.r2r_paths,
            "list_pio": engine.list_pio,
            "deepest_cone_output": engine.deepest_cone_output,
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
        a massive string — plain text or JSON.
        """
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
        notice = (
            f"The output from '{tool_name}' is too large to fit in LLM context. "
            f"Full details saved to {log_path}"
        )

        if result.lstrip().startswith("{"):
            try:
                obj = json.loads(result)
                compact: dict = {"notice": notice, "saved_to_file": log_path}
                for k, v in obj.items():
                    if isinstance(v, (str, int, float, bool)) or v is None:
                        compact[k] = v
                    elif isinstance(v, list):
                        compact[f"{k}_count"] = len(v)
                        compact[f"{k}_sample"] = v[:3]
                    elif isinstance(v, dict) and len(json.dumps(v)) < 500:
                        compact[k] = v
                return json.dumps(compact, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass

        lines = result.splitlines()
        total_lines = len(lines)
        summary = {
            "notice": notice,
            "total_lines": total_lines,
            "saved_to_file": log_path,
            "samples": lines[:5],
        }
        return json.dumps(summary, ensure_ascii=False, indent=2)

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

import logging
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
            return str(result)
        except TypeError as exc:
            # Wrong argument names — the LLM hallucinated a parameter.
            return (
                f"Error: tool '{tc.name}' was called with invalid arguments "
                f"{tc.arguments}: {exc}"
            )
        except Exception as exc:
            logger.error("Tool '%s' raised an exception: %s", tc.name, exc)
            return f"Error executing '{tc.name}': {exc}"

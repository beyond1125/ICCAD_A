#!/usr/bin/env python3
"""Dry-run test for the CADA EDA agent.

Runs the full main loop against tests/test_input.txt using a
DeterministicLLMClient that simulates tool-calling without any real API key.

Usage (from the project root):
    python3 tests/integration_tests/run_test.py

What it exercises:
    1. Testcase init   → #RESPONSE 1  (no LLM involved)
    2. load_design     → full agentic round-trip → #RESPONSE 2
    3. analyze_depth   → full agentic round-trip → #RESPONSE 3
    4. write_design    → full agentic round-trip → #RESPONSE 4
    5. test8.log matches stdout exactly
"""

import os
import re
import sys
import io
import unittest.mock as mock
from pathlib import Path

# Ensure the project root and src/ are importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent.llm_client import LLMResponse, ToolCall  # noqa: E402


# ── argument extractors (defined before the class that uses them) ─────────────

def _extract_filepath(text: str) -> dict:
    """Pull 'dir/file.v' from messages like: load 'test8.v' in 'design/netlist/'"""
    dir_m  = re.search(r"director(?:y|ies)[^\w]*['\"]?([^\s'\"]+)['\"]?", text, re.I)
    file_m = re.search(r"['\"]?([\w./]+\.v)['\"]?", text, re.I)
    filename = file_m.group(1) if file_m else "design.v"
    if dir_m:
        base = os.path.basename(filename)
        filename = dir_m.group(1).rstrip("/") + "/" + base
    return {"filepath": filename}


def _extract_filepath_out(text: str) -> dict:
    m = re.search(r"['\"]?([\w./]+\.v)['\"]?", text, re.I)
    return {"filepath": m.group(1) if m else "output.v"}


def _extract_depth_args(text: str) -> dict:
    m = re.search(r'from\s+(?:input\s+)?(\w+)\s+to\s+(?:output\s+)?(\w+)', text, re.I)
    if m:
        return {"start_node": m.group(1), "end_node": m.group(2)}
    return {"start_node": "in0", "end_node": "out3"}  # changed default to out3


# ── deterministic LLM (no API key required) ───────────────────────────────────

_RULES = [
    (re.compile(r'\bload\b|\bread\b',   re.I), "load_design",   _extract_filepath),
    (re.compile(r'\bdepth\b|\bpath\b',  re.I), "analyze_depth", _extract_depth_args),
    (re.compile(r'\bwrite\b|\boutput\b', re.I), "write_design", _extract_filepath_out),
]


class DeterministicLLMClient:
    """Rule-based LLM stub — simulates the two-step tool-call agentic loop.

    Round 1: inspects the user message and returns a ToolCall.
    Round 2: receives the tool result and returns a plain-text summary.
    """

    def __init__(self, config, tools):
        pass  # config/tools ignored — we are fully deterministic

    def chat(self, messages: list) -> LLMResponse:
        tool_results = [m for m in messages if m.get("role") == "tool"]

        if not tool_results:
            return self._pick_tool(messages)
        return self._summarise(tool_results)

    def _pick_tool(self, messages: list) -> LLMResponse:
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                user_text = m["content"]
                break

        for pattern, tool_name, arg_builder in _RULES:
            if pattern.search(user_text):
                args = arg_builder(user_text)
                tc = ToolCall(id=f"call_{tool_name}", name=tool_name, arguments=args)
                raw = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": str(args)},
                    }],
                }
                return LLMResponse(
                    text=None, tool_calls=[tc],
                    raw_message=raw, finish_reason="tool_calls",
                )

        # No matching tool — answer without calling anything.
        text = "No EDA operation needed for this request."
        return LLMResponse(
            text=text, tool_calls=[],
            raw_message={"role": "assistant", "content": text},
            finish_reason="stop",
        )

    def _summarise(self, tool_results: list) -> LLMResponse:
        text = "\n".join(m["content"] for m in tool_results)
        return LLMResponse(
            text=text, tool_calls=[],
            raw_message={"role": "assistant", "content": text},
            finish_reason="stop",
        )


# ── helpers ───────────────────────────────────────────────────────────────────

SEP = "─" * 60


def _run_main_loop(config_path: str, stdin_lines: list[str]) -> str:
    """Run the main request loop and return everything written to stdout."""
    from utils.config import Config
    from utils.io_manager import IOManager, extract_testcase_name
    from eda_engine.engine import EDAEngine
    from agent.planner import Planner

    config = Config.from_yaml(config_path)
    io_mgr = IOManager()
    engine = EDAEngine()
    planner = Planner(config, engine)

    captured = io.StringIO()

    # Redirect stdout so IOManager writes to our buffer instead of the terminal.
    with mock.patch("sys.stdout", captured):
        try:
            for raw_line in stdin_lines:
                line = raw_line.rstrip("\n").strip()
                if not line:
                    continue

                case_name = extract_testcase_name(line)
                if case_name:
                    io_mgr.init_testcase(case_name)
                    planner.reset()
                    response = (
                        f'Acknowledged. Initialized testcase "{case_name}". '
                        f'All subsequent responses will be recorded to '
                        f'testcase/{case_name}/{case_name}.log.\n'
                        f'Design state is empty and ready for commands.'
                    )
                else:
                    response = planner.process(line)

                io_mgr.write_response(response)
        finally:
            io_mgr.close()

    return captured.getvalue()


# ── main test ─────────────────────────────────────────────────────────────────

def run():
    os.chdir(PROJECT_ROOT)  # log file is written relative to cwd

    test_input = PROJECT_ROOT / "tests" / "integration_tests" / "test_input.txt"
    config_path = str(PROJECT_ROOT / "config.yaml")
    log_path = PROJECT_ROOT / "testcase" / "test8" / "test8.log"

    log_path.unlink(missing_ok=True)
    (PROJECT_ROOT / "testcase" / "test8").mkdir(parents=True, exist_ok=True)

    stdin_lines = test_input.read_text(encoding="utf-8").splitlines(keepends=True)

    print(SEP)
    print("INPUT (simulated stdin)")
    print(SEP)
    for i, line in enumerate(stdin_lines, 1):
        print(f"  [{i}] {line.rstrip()}")

    # Patch LLMClient globally before Planner imports it
    with mock.patch("agent.llm_client.LLMClient", DeterministicLLMClient):
        stdout_text = _run_main_loop(config_path, stdin_lines)

    print()
    print(SEP)
    print("STDOUT (what the grader sees)")
    print(SEP)
    print(stdout_text)

    print(SEP)
    print("LOG FILE  testcase/test8/test8.log")
    print(SEP)
    log_text = log_path.read_text() if log_path.exists() else "(missing!)"
    print(log_text)

    # ── assertions ────────────────────────────────────────────────────────────
    errors = []

    responses = re.findall(r"#RESPONSE (\d+)", stdout_text)
    ends      = re.findall(r"#END (\d+)",      stdout_text)

    if responses != ["1", "2", "3", "4"]:
        errors.append(f"Expected response IDs [1,2,3,4], got {responses}")
    if ends != responses:
        errors.append(f"#END ids {ends} don't match #RESPONSE ids {responses}")
    if 'Initialized testcase "test8"' not in stdout_text:
        errors.append("Missing testcase acknowledgment in response 1")
    if not log_path.exists():
        errors.append("testcase/test8/test8.log was not created")
    elif log_path.read_text() != stdout_text:
        errors.append("testcase/test8/test8.log content does not match stdout")

    print(SEP)
    if errors:
        print("RESULT: FAIL")
        for e in errors:
            print(f"  ✗  {e}")
        sys.exit(1)
    else:
        print("RESULT: PASS")
        print(f"  ✓  {len(responses)} responses with matching #RESPONSE / #END tags")
        print(f"  ✓  testcase/test8/test8.log == stdout")
        print(f"  ✓  testcase acknowledgment in response 1")


if __name__ == "__main__":
    run()

#!/usr/bin/env python3
"""Entry point for the CADA EDA agent.

Invocation (Section 3.1):
    ./cada0001_alpha -config <config_file_path>

Reads natural-language requests from stdin one line at a time.
Detects testcase-initialisation messages, resets state, and opens the log.
All other lines are sent to the Planner, and every response is printed to
stdout (and the active log file) wrapped in #RESPONSE / #END tags.

The grader only sends the next request after it detects #END <id> on stdout,
so IOManager flushes stdout immediately after writing each #END tag.
"""

import argparse
import logging
import sys

from config import Config
from io_manager import IOManager, extract_testcase_name
from eda_engine.engine import EDAEngine
from agent.planner import Planner

# Warnings and errors go to stderr so they do not pollute stdout.
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cada0001_alpha",
        description="LLM-Assisted Netlist Exploration and Transformation Agent",
    )
    parser.add_argument(
        "-config",
        required=True,
        metavar="<config_file_path>",
        help="Path to the YAML configuration file",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # ── initialise subsystems ─────────────────────────────────────────────────
    try:
        config = Config.from_yaml(args.config)
    except Exception as exc:
        sys.exit(f"Failed to load config '{args.config}': {exc}")

    io_mgr = IOManager()
    engine = EDAEngine()
    planner = Planner(config, engine)

    # ── main request loop ─────────────────────────────────────────────────────
    try:
        while True:
            line = sys.stdin.readline()
            if not line:          # EOF — contest harness closed stdin
                break

            line = line.rstrip("\n").strip()
            if not line:          # blank line — skip silently
                continue

            case_name = extract_testcase_name(line)

            if case_name:
                # ── testcase initialisation ───────────────────────────────────
                # Open log, reset response ID, reset engine state.
                # The acknowledgment IS response 1 for this testcase.
                io_mgr.init_testcase(case_name)
                planner.reset()
                response = (
                    f'Acknowledged. Initialized testcase "{case_name}". '
                    f'All subsequent responses will be recorded to {case_name}.log.\n'
                    f'Design state is empty and ready for commands.'
                )
            else:
                # ── normal EDA request ────────────────────────────────────────
                try:
                    response = planner.process(line)
                except Exception as exc:
                    logger.exception("Unhandled error while processing request")
                    response = f"Internal error while processing request: {exc}"

            io_mgr.write_response(response)

    except KeyboardInterrupt:
        pass
    finally:
        io_mgr.close()


if __name__ == "__main__":
    main()

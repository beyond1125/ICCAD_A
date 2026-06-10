"""Project path helpers — all paths relative to the repository root."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
TESTCASE_DIR = PROJECT_ROOT / "testcase"

#!/usr/bin/env python3
"""Build the C++ parser for the current platform."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(ROOT, "core")


def _output_path() -> str:
    if sys.platform == "win32":
        return os.path.join(CORE_DIR, "eda_core.exe")
    return os.path.join(CORE_DIR, "eda_core")


def main() -> None:
    compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise SystemExit("No C++ compiler found. Install g++ or set CXX.")

    # Get all .cpp files in the core directory
    sources = [
        os.path.join(CORE_DIR, f) 
        for f in os.listdir(CORE_DIR) 
        if f.endswith(".cpp") and f != "parser.cpp"
    ]

    out = _output_path()
    cmd = [compiler, "-std=c++17"] + sources + ["-o", out]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"Built: {out}")


if __name__ == "__main__":
    main()

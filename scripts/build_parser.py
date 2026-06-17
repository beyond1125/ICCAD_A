#!/usr/bin/env python3
"""Build the C++ parser for the current platform."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARSER_DIR = os.path.join(ROOT, "src", "eda_engine", "parser")

def _output_path() -> str:
    if sys.platform == "win32":
        return os.path.join(PARSER_DIR, "parser_cpp.exe")
    return os.path.join(PARSER_DIR, "parser_cpp")

def main() -> None:
    compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise SystemExit("No C++ compiler found. Install g++ or set CXX.")

    out = _output_path()
    cpp_files = [f for f in glob.glob(os.path.join(PARSER_DIR, "*.cpp")) if os.path.basename(f) != "parser.cpp"]
    cmd = [compiler, "-std=c++17"] + cpp_files + ["-o", out]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"Built: {out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Faithful grader simulator for ICCAD Problem A (spec section 3).

Unlike run_tests.py (pexpect/pty) this uses plain pipes — same as a real
harness — so stdout buffering bugs are NOT masked by pty line-buffering.
Feeds prompt lines one at a time, gated on seeing '#END <n>' on stdout.

Usage: python3 scripts/grader_sim.py <testcase_name> [--timeout N] [--config PATH]
Can be run from any CWD (ROOT resolves from the script location).
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path("/tmp/grader_sim")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--timeout", type=int, default=300, help="per-turn timeout (s)")
    ap.add_argument("--config", default="config.yaml", help="config file passed to main.py")
    a = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)

    prompt_path = ROOT / "testcase" / a.case / "prompt.txt"
    lines = [ln.strip() for ln in prompt_path.read_text().splitlines() if ln.strip()]
    print(f"[grader_sim] {a.case}: {len(lines)} turns, pipe-based, "
          f"gated on #END, timeout {a.timeout}s/turn", flush=True)

    stderr_path = OUT_DIR / f"{a.case}_grader_sim.stderr"
    stderr_f = open(stderr_path, "w")
    proc = subprocess.Popen(
        [sys.executable, "main.py", "-config", a.config],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_f,
        text=True, bufsize=1, cwd=str(ROOT), env=os.environ,
    )

    transcript = []
    ok = True
    try:
        for turn, line in enumerate(lines, start=1):
            short = line if len(line) < 70 else line[:67] + "..."
            print(f"  -> turn {turn}: {short}", flush=True)
            t0 = time.time()
            proc.stdin.write(line + "\n")
            proc.stdin.flush()

            end_tag = f"#END {turn}"
            buf = []
            while True:
                if time.time() - t0 > a.timeout:
                    print(f"  [!] TIMEOUT waiting for '{end_tag}'", flush=True)
                    ok = False
                    break
                out_line = proc.stdout.readline()
                if out_line == "":
                    print(f"  [!] EOF from program while waiting for '{end_tag}'",
                          flush=True)
                    ok = False
                    break
                buf.append(out_line)
                if out_line.strip() == end_tag:
                    break
            transcript.append("".join(buf))
            if not ok:
                break
            print(f"  <- turn {turn}: got {end_tag} in {time.time()-t0:.1f}s",
                  flush=True)
        proc.stdin.close()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
        stderr_f.close()
        stderr_tail = stderr_path.read_text()[-2000:]

    out_file = OUT_DIR / f"{a.case}_grader_sim.log"
    out_file.write_text("".join(transcript))
    print(f"[grader_sim] transcript -> {out_file}", flush=True)
    if stderr_tail.strip():
        print(f"[grader_sim] stderr tail:\n{stderr_tail}", flush=True)
    print(f"[grader_sim] result: {'COMPLETE' if ok else 'FAILED'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

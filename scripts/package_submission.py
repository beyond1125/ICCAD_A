#!/usr/bin/env python3
"""Build a self-contained TSRI delivery package.

Per the official contest Q&A (A5.1/A6.1, revised — docs/CONTEST_QA.md):
Docker submissions are NOT supported. The deliverable must run directly on
the TSRI evaluation machine, and evaluation-time network access is limited
to the model provider APIs (no `pip install`, no `git clone`). Third-party
binaries may be bundled with no size limit (A15).

This script produces `dist/cada1066_alpha_pkg/`, a directory that is meant
to be copied to the TSRI machine as-is and run with no further setup beyond
having a compatible system `python3` on PATH:

    dist/cada1066_alpha_pkg/
    ├── cada1066_alpha          # entry point (spec sec 3.1 invocation)
    ├── main.py
    ├── config.yaml
    ├── requirements.txt
    ├── PACKAGING.md
    ├── src/                    # runtime code, no __pycache__
    │   └── eda_engine/parser/parser_cpp   # prebuilt for THIS machine's arch/glibc
    ├── vendor/                 # `pip install --target` of requirements.txt
    └── tools/abc/abc           # prebuilt Berkeley ABC binary

Usage:
    python3 scripts/package_submission.py [--out DIST_DIR] [--skip-vendor]
                                           [--skip-parser-build]

`--skip-vendor` / `--skip-parser-build` are for fast iteration on this
script itself; a real delivery build should run with neither flag.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "dist" / "cada1066_alpha_pkg"

# Main-checkout fallback for tools/abc — this worktree may not have it checked
# out / built locally, but the primary dev checkout does.
MAIN_CHECKOUT_ABC = Path("/home/cynth19/ICCAD_A/tools/abc/abc")

RUNTIME_FILES = ["main.py", "config.yaml", "requirements.txt"]
RUNTIME_DIRS = ["src"]  # copied minus __pycache__ / *.pyc


def _run(cmd: list[str], **kwargs) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def _copy_runtime_code(out_dir: Path) -> None:
    """Copy main.py, config.yaml, requirements.txt, and src/ (no __pycache__)."""
    for name in RUNTIME_FILES:
        src = ROOT / name
        if not src.is_file():
            raise SystemExit(f"Missing expected runtime file: {src}")
        shutil.copy2(src, out_dir / name)
        print(f"copied {name}")

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        ignored = set()
        for n in names:
            if n in ("__pycache__", ".pytest_cache") or n.endswith((".pyc", ".pyo", ".pyd")):
                ignored.add(n)
        return ignored

    for name in RUNTIME_DIRS:
        src = ROOT / name
        dst = out_dir / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=_ignore)
        print(f"copied {name}/ (no __pycache__)")


def _build_parser(out_dir: Path, skip: bool) -> None:
    """Compile parser_cpp fresh, then ensure it's present in the package.

    We build in the source tree first (scripts/build_parser.py always
    compiles into src/eda_engine/parser/ relative to ROOT) then the copy of
    src/ already landed in out_dir picks it up IF we build before copying.
    To keep the two steps independent and re-runnable in either order, we
    build first here and then explicitly copy the binary into the package's
    same relative path, overwriting whatever _copy_runtime_code already put
    there (stale or absent).
    """
    parser_dir_src = ROOT / "src" / "eda_engine" / "parser"
    bin_name = "parser_cpp.exe" if sys.platform == "win32" else "parser_cpp"
    built_path = parser_dir_src / bin_name

    if not skip:
        _run([sys.executable, str(ROOT / "scripts" / "build_parser.py")])
    if not built_path.is_file():
        raise SystemExit(
            f"parser_cpp not found at {built_path} after build "
            f"(pass --skip-parser-build only if it already exists and you "
            f"know it's current)."
        )

    dst_path = out_dir / "src" / "eda_engine" / "parser" / bin_name
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built_path, dst_path)
    dst_path.chmod(dst_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"prebuilt parser_cpp -> {dst_path}")


def _copy_abc(out_dir: Path) -> None:
    """Copy the prebuilt Berkeley ABC binary into tools/abc/ inside the package.

    engine.py's _find_abc_binary() walks upward from src/eda_engine/ looking
    for abc/abc or tools/abc/abc, so tools/abc/abc at the package root is the
    right relative location.
    """
    candidates = [
        ROOT / "tools" / "abc" / "abc",
        MAIN_CHECKOUT_ABC,
    ]
    src_abc = next((c for c in candidates if c.is_file()), None)
    if src_abc is None:
        raise SystemExit(
            "No ABC binary found. Checked: "
            + ", ".join(str(c) for c in candidates)
            + ". Build tools/abc (see docs/Technical_specification_document.md "
            "sec 9.1) or point this script at a machine that has it."
        )

    dst_dir = out_dir / "tools" / "abc"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_path = dst_dir / "abc"
    shutil.copy2(src_abc, dst_path)
    dst_path.chmod(dst_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    note = " (copied from main checkout, not this worktree)" if src_abc == MAIN_CHECKOUT_ABC else ""
    print(f"prebuilt ABC binary -> {dst_path}{note}")
    return src_abc


def _vendor_dependencies(out_dir: Path, skip: bool) -> None:
    """pip install --target vendor/ -r requirements.txt.

    Deliberately NOT a venv: venvs symlink (or hardlink/copy, depending on
    platform) back to the interpreter that created them and carry an
    activation script tied to that interpreter's absolute path — both break
    when the directory is moved to a machine with a different python3
    location/version. `pip install --target` instead drops plain importable
    packages into a directory that any compatible interpreter can use via
    PYTHONPATH, which is what the wrapper script sets up.
    """
    vendor_dir = out_dir / "vendor"
    if skip:
        print("--skip-vendor: leaving vendor/ untouched")
        return
    if vendor_dir.exists():
        shutil.rmtree(vendor_dir)
    vendor_dir.mkdir(parents=True)
    _run([
        sys.executable, "-m", "pip", "install",
        "--target", str(vendor_dir),
        "-r", str(ROOT / "requirements.txt"),
    ])
    # pip byte-compiles as it installs, littering vendor/ with __pycache__.
    # Harmless but not worth shipping -- strip it for a clean package tree.
    removed = 0
    for cache_dir in vendor_dir.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)
        removed += 1
    print(f"vendored dependencies -> {vendor_dir} (stripped {removed} __pycache__ dirs)")


def _write_entry_point(out_dir: Path) -> None:
    script = out_dir / "cada1066_alpha"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# Contest entry point (spec sec 3.1): ./cada1066_alpha -config <config_file_path>\n"
        "# Self-contained package build (scripts/package_submission.py, P0-1):\n"
        "# no venv, no pip install at eval time (A5.1/A6.1) -- resolve this\n"
        "# script's own directory, prepend the vendored dependencies to\n"
        "# PYTHONPATH, then exec the real entry point with system python3.\n"
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'export PYTHONPATH="$SCRIPT_DIR/vendor:$PYTHONPATH"\n'
        'exec python3 "$SCRIPT_DIR/main.py" "$@"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"entry point -> {script}")


def _write_packaging_doc(out_dir: Path, abc_source: Path) -> None:
    py_version = sys.version.split()[0]
    py_impl = platform.python_implementation()
    machine = platform.machine()
    system = platform.system()
    libc = ""
    try:
        libc = " ".join(platform.libc_ver())
    except Exception:
        pass

    doc = f"""# PACKAGING.md — cada1066_alpha delivery package

Generated by `scripts/package_submission.py` (P0-1, docs/PLAN_QA_fixes.md).

## What this directory contains

```
cada1066_alpha_pkg/
├── cada1066_alpha              # entry point: ./cada1066_alpha -config <config>
├── main.py, config.yaml, requirements.txt
├── src/                        # runtime code (no __pycache__)
│   └── eda_engine/parser/parser_cpp   # prebuilt for THIS build machine
├── vendor/                     # `pip install --target` of requirements.txt
│                                #  (NOT a venv -- see caveats below)
└── tools/abc/abc                # prebuilt Berkeley ABC binary
```

No `.env` is packaged (it holds API secrets and is gitignored). Set
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in the evaluation environment before
invoking the entry point; `src/utils/config.py` expands `${{VAR}}` placeholders
in `config.yaml` from real environment variables (a `.env` at the package
root is also honored if the evaluator chooses to drop one there, but is not
required and is not shipped by this script).

## Why this shape (A5.1/A6.1)

The official Q&A revision states Docker submissions are not supported: the
program must run directly on the TSRI machine, and evaluation-time network
access is open only to the model provider APIs (no `pip install`, no `git
clone`). Third-party binaries may be bundled with no size limit (A15). This
package is therefore fully self-contained: vendored Python dependencies,
a prebuilt C++ parser binary, and a prebuilt ABC binary, wired together by
`cada1066_alpha`, a thin wrapper that prepends `vendor/` to `PYTHONPATH` and
execs `python3 main.py` with system Python -- no venv, no build step, no
network access required at evaluation time.

## Build-machine fingerprint (compiled artifacts are version/arch specific)

- `python3 -V`: Python {py_version} ({py_impl})
- `uname -m`: {machine}
- `platform.system()`: {system}
- `libc_ver()`: {libc or 'n/a (not glibc-reporting platform)'}
- ABC binary source: `{abc_source}`

`vendor/` contains compiled wheels (notably `pydantic_core`, a Rust
extension pulled in transitively by the `anthropic`/`openai` SDKs) built
for the exact Python version, CPU architecture, and glibc version above.
Pure-Python packages in `vendor/` are portable; the compiled ones are not.

## TSRI prerequisites

- System `python3` >= 3.10, matching architecture ({machine}) and a glibc
  version compatible with the one recorded above (compiled wheels in
  `vendor/` link against it). Do NOT rely on a venv; none is shipped or
  required.
- No outbound network needed except to the model provider API endpoint(s)
  configured in `config.yaml` (e.g. `api.anthropic.com`). No `pip install`,
  no `git clone` happens at run time.
- `tools/abc/abc` and `src/eda_engine/parser/parser_cpp` must be executable
  (this script sets the executable bit; verify it survived any transfer
  step, e.g. `chmod +x` after unzip if the transfer method strips
  permissions).

## If TSRI python3 differs majorly from the build machine above

The compiled wheels in `vendor/` (pydantic-core and any other C/Rust
extension pulled in by the `anthropic`/`openai` SDKs) are version- and
arch-specific and will fail to import on a sufficiently different target
(different Python minor version, CPU architecture, or glibc major version).
Two fallbacks, in order of preference (neither is implemented by this
script):

1. **Rebuild `vendor/` on a matching machine.** Run this same
   `scripts/package_submission.py` on a machine with the same `python3`
   version/arch/glibc as the TSRI target (or in a container/chroot that
   matches it), then ship that `vendor/` instead.
2. **PyInstaller single-file build.** More self-contained (bundles the
   interpreter itself), but the `anthropic`/`openai` SDKs use dynamic
   imports in places, and compatibility needs to be verified empirically
   before relying on it; this is the fallback PLAN_QA_fixes.md's P0-1
   flagged as higher-risk and deferred (documented here, not implemented).

## Smoke test

From a clean directory outside the repo (so relative paths cannot
accidentally resolve against the dev checkout), with a testcase directory
copied alongside:

```bash
export ANTHROPIC_API_KEY=...   # evaluator's key; never commit this
printf '%s\\n' \\
  'This is the beginning of a new testcase. The case name is test02.' \\
  'Please load the design from the file test02.v located in the directory testcase/test02/.' \\
  'Please count all the gates in this design and report the total count broken down by gate type (AND, OR, NOT, NAND, NOR, XOR, XNOR, BUF, DFF).' \\
  'Please write the current design to the output file test02_out.v.' \\
| ./cada1066_alpha_pkg/cada1066_alpha -config cada1066_alpha_pkg/config.yaml
```

Expect 4 `#RESPONSE`/`#END` turns on stdout, `test02_out.v` written under the
copied `testcase/test02/` directory, and `test02.log` in the current working
directory (per spec sec 3.1/A5.3: log path is CWD-relative, not
package-relative).
"""
    (out_dir / "PACKAGING.md").write_text(doc)
    print(f"wrote {out_dir / 'PACKAGING.md'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output package directory")
    ap.add_argument("--skip-vendor", action="store_true", help="don't re-run pip install --target")
    ap.add_argument("--skip-parser-build", action="store_true", help="don't recompile parser_cpp")
    args = ap.parse_args()

    out_dir: Path = args.out
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    print(f"=== Packaging into {out_dir} ===")
    _copy_runtime_code(out_dir)
    _build_parser(out_dir, args.skip_parser_build)
    abc_source = _copy_abc(out_dir)
    _vendor_dependencies(out_dir, args.skip_vendor)
    _write_entry_point(out_dir)
    _write_packaging_doc(out_dir, abc_source)

    print(f"=== Done: {out_dir} ===")
    du = subprocess.run(["du", "-sh", str(out_dir)], capture_output=True, text=True)
    print(du.stdout.strip())


if __name__ == "__main__":
    main()

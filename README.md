# ICCAD 2026 Problem A: LLM-Assisted Netlist Transformation

An LLM-based EDA agent that processes gate-level Verilog netlists. The agent interprets natural-language instructions, calls structured tools backed by a C++ engine, and produces transformed netlists.

## Project Structure

```text
ICCAD_A/
├── src/
│   ├── agent/
│   │   ├── planner.py         # LLM tool-calling loop; conversation history management
│   │   ├── llm_client.py      # API wrapper (Anthropic / OpenAI)
│   │   └── tool_spec.py       # Tool definitions exposed to the LLM
│   │
│   ├── eda_engine/
│   │   ├── engine.py          # Python interface to the C++ parser
│   │   └── parser/            # C++ netlist engine
│   │       ├── main.cpp        # CLI entry point; action dispatch
│   │       ├── graph.cpp/hpp   # Graph representation and all analysis/transform logic
│   │       ├── verilog_parser.cpp/hpp
│   │       ├── verilog_writer.cpp/hpp
│   │       ├── node.cpp/hpp
│   │       ├── types.hpp
│   │       └── utils.cpp
│   │
│   └── utils/
│       ├── config.py          # YAML + .env config parsing
│       ├── io_manager.py      # #RESPONSE/#END output format and logging
│       └── paths.py           # Project root path constants
│
├── scripts/
│   ├── build_parser.py        # Cross-platform C++ compiler script
│   ├── run_all_llm.py         # Primary test runner: full LLM-driven sweep
│   ├── check_results.py       # Hard-requirement grading checker
│   ├── eval_harness.py        # Ground-truth-free evaluation harness
│   ├── check_answers.py       # Analysis-answer correctness grader
│   ├── netlist_oracle.py      # Independent oracle used by check_answers.py
│   ├── grader_sim.py          # Faithful single-case grader simulator (debugging)
│   ├── package_submission.py  # Builds the self-contained TSRI delivery package
│   └── run_tests.py           # Legacy pexpect-based runner
│
├── testcase/                  # Test cases (test01–test40)
│   └── test0x/
│       ├── prompt.txt         # Turn-by-turn instructions
│       └── test0x.v           # Input Verilog netlist
│
├── docs/
│   ├── Technical_specification_document.md  # Class/algorithm/data-structure spec
│   ├── System_design_document.md            # Architecture & system design
│   ├── OPEN_QUESTIONS.md                    # Spec-ambiguity decisions
│   ├── REPORT_transform.md                  # Transform tools/testcases/algorithms
│   └── EVAL_HARNESS.md                      # Evaluation harness design notes
│
├── tools/abc/                 # Berkeley ABC (clone separately)
├── tests/                     # Integration test (CI) + unit smoke test
├── .claude/                   # Claude Code project settings (rules, skills)
├── CLAUDE.md                  # Claude Code project setup
├── cada1066_alpha             # Contest entry point (executable wrapper)
├── main.py                    # System entry point
├── config.yaml                # Runtime configuration (model, API provider)
├── Dockerfile                 # Dev-only build repro (NOT the delivery path — see Delivery below)
└── requirements.txt
```

## Setup

**1. Create virtual environment and install dependencies:**
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> On the shared dev box, use system `python3` instead — the checked-in `./venv`
> is broken (missing deps). See `CLAUDE.md` for the full list of hard rules
> that apply to that machine.

**2. Compile the C++ parser:**
```bash
python scripts/build_parser.py
```
Outputs `src/eda_engine/parser/parser_cpp` (Linux/macOS) or `parser_cpp.exe` (Windows).

**3. Set API keys — create `.env`:**
```text
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
```

**4. (Optional) Berkeley ABC for equivalence checking:**
```bash
cd tools && git clone https://github.com/berkeley-abc/abc.git
cd abc && make
```

## Delivery (TSRI submission)

Per the official contest Q&A (A5.1/A6.1, revised — `docs/CONTEST_QA.md`),
**Docker submissions are not supported**: the program must run directly on
the TSRI evaluation machine, and evaluation-time network access is limited
to the model provider APIs (no `pip install`). `Dockerfile` /
`docker-compose.yml` are therefore **development-only tools** (local
reproducible builds, CI) — they are not the delivery path.

The actual deliverable is built by `scripts/package_submission.py`, which
produces a self-contained `dist/cada1066_alpha_pkg/` directory: runtime code,
vendored Python dependencies (`pip install --target`, not a venv — venvs
hardcode the build machine's interpreter path and break when moved), a
freshly-compiled `parser_cpp`, and a prebuilt Berkeley ABC binary under
`tools/abc/abc`. Copy that directory to the TSRI machine and run it with a
compatible system `python3` — no further install step, no network access
needed beyond the configured model API.

```bash
python3 scripts/package_submission.py        # -> dist/cada1066_alpha_pkg/
./dist/cada1066_alpha_pkg/cada1066_alpha -config dist/cada1066_alpha_pkg/config.yaml
```

See `dist/cada1066_alpha_pkg/PACKAGING.md` (generated) for the build
machine's Python/arch/glibc fingerprint, TSRI prerequisites, and the smoke
test command; see `docs/Technical_specification_document.md` §9.3 for the
full packaging design and honest compatibility caveats (compiled wheels like
`pydantic-core` are version/arch-specific — the documented fallback is
rebuilding `vendor/` on a matching machine, or PyInstaller as a
higher-risk alternative).

## Usage

The contest entry point is the `cada1066_alpha` wrapper (spec §3.1):

```bash
./cada1066_alpha -config config.yaml
```

Equivalently, pipe a prompt file into `main.py` directly to run a single
testcase interactively:

```bash
cat testcase/test02/prompt.txt | python3 main.py -config config.yaml
```

Output is written to `test02.log` (current working directory, spec-mandated)
and mirrored to `testcase/test02/test02.log` when that directory exists.

For faithful, pipe-gated single-case debugging (same `#END`-gated protocol a
real grader uses, full LLM/tool-call trace under `/tmp/grader_sim/`):

```bash
python3 scripts/grader_sim.py test02
```

## Running Tests

**`scripts/run_all_llm.py` is the primary runner** — it drives the real LLM
agent end-to-end for one, a range, or all 40 testcases:

```bash
# Single testcase
python3 scripts/run_all_llm.py --case 2

# Range of testcases
python3 scripts/run_all_llm.py --from 21 --to 30

# All 40 testcases
python3 scripts/run_all_llm.py

# Custom per-case timeout (default: 900s; test12 alone legitimately needs ~10 min)
python3 scripts/run_all_llm.py --timeout 900
```

Status legend: `OK` (turns completed + output file exists) · `OK*` (turns
completed, no output file) · `PARTIAL` (ran out of turns) · `APIERR`
(provider/auth failure — two in a row aborts the sweep) · `ERR`/`TIMEOUT`/`CRASH`
(non-zero exit / per-case timeout / runner exception). The summary also
reports prompt/completion/total token columns and API-call counts per case.
`OK` means the protocol completed — it is **not** a score; always follow with
`check_results.py` (and optionally `eval_harness.py`) before trusting a run.

`scripts/run_tests.py` is the legacy pexpect-based runner, kept for reference.

## Output Files

| File | Description |
|------|-------------|
| `<case>.log` | Agent's own log, spec-mandated (written to CWD; copied into `testcase/<case>/<case>.log` when that directory exists) |
| `testcase/<case>/<case>_llm_run.log` | Full `#RESPONSE`/`#END` stdout transcript captured by `run_all_llm.py` |
| `testcase/<case>/<case>_out.v` | Output netlist written by the agent |
| `src/eda_engine/parser/parser_cpp` | Compiled C++ binary (not committed) |

## Evaluation

Three independent, complementary evaluators run after an agent run. None of them trusts the C++ engine that produced the output: each re-derives its checks from scratch.

**`scripts/check_results.py` — hard-requirement grading checker.**
Parses each output netlist with a small self-contained mini-parser (not the production C++ engine) and checks the hard requirements implied by `prompt.txt`: functional equivalence to the original netlist (via `write_blif` + ABC `cec`, flop-cut), max-fanout limits, gate-basis purity (whole design or a cone), forbidden gate types, and per-signal dedicated-buffer trees. Soft/ambiguous requirements (renames, back-to-back inverters, buffers surviving later transforms) are reported as `warn` and do not fail a case. Prints a `PASS`/`FAIL`/`PASS?` line per case plus a per-check breakdown, and exits non-zero if any case has a hard-requirement failure.

```bash
python3 scripts/check_results.py --case test26
python3 scripts/check_results.py --from 21 --to 30
python3 scripts/check_results.py --all
```

**`scripts/eval_harness.py` — ground-truth-free evaluation harness.**
Scores the system with no external answer key, using three self-generated sources of truth: (1) **equivalence** — ABC `cec` proves each `<case>_out.v` is functionally equivalent to the original; (2) **invariants** on the output — flip-flop count preserved, max gate fanout, round-trip stability (write → reload → same gate count); (3) **differential** checks — an independent Python netlist oracle (built into the script) is compared against the C++ tool's own `count_gates` and `list_paths` output on the *original* netlist; a disagreement is a real bug, and a tool timeout where the oracle answers instantly is itself a finding (e.g. path enumeration that doesn't scale). Prints a per-case status table and summary counts; exits non-zero unless every case is `PASS`/`NO-OUTPUT`/`CHECK`.

```bash
python3 scripts/eval_harness.py                  # every testcase found
python3 scripts/eval_harness.py --from 21 --to 30
python3 scripts/eval_harness.py --case 12
python3 scripts/eval_harness.py --skip-paths      # skip the slower tool path checks
```

**`scripts/check_answers.py` — analysis-answer correctness grader.**
Grades the agent's recorded answers (`<case>.log`) to analysis questions — gate
counts, path existence, logic depth, fanout, cones, signal equivalence — against
`scripts/netlist_oracle.py`, an independent pure-Python ground truth (own parser,
topological-DP levelization and path counting, own BLIF writer feeding ABC for
SAT-level questions). Every prompt line is classified by question type; answers
are only graded while the design state still equals the original netlist (turns
after the first transform are `SKIPPED-STATE`). Numeric mismatches are
adjudicated against `parser_cpp` before being called wrong: a claim that matches
the tool's own definition grades `DIVERGENT` (definition difference), not
`WRONG`. Claim extraction is scoped to the answer, not the whole response:
fanin context ("2 inputs (driven by g2 and g64)", "Direct Fanin: ..." lines) is
scrubbed before successor/fanout claims are read, an explicit "no immediate
successors" counts as an empty-list claim, and for yes/no questions a question
echo ("to determine if they are equivalent ...") or a hedged verdict ("most
likely not equivalent") is no claim at all -> `UNVERIFIED`, not a polarity.
Exits non-zero if any graded turn is `WRONG`.

```bash
python3 scripts/check_answers.py --case test18
python3 scripts/check_answers.py --all
python3 scripts/check_answers.py --selftest       # synthetic-fixture self check
```

Together with `run_all_llm.py` these form a four-layer stack — protocol
completion → hard requirements → goal predicates → answer correctness — run
them in that order; no single layer is a score on its own.

See `docs/EVAL_HARNESS.md` for further discussion of the harness's design, and
`docs/System_design_document.md` / `docs/Technical_specification_document.md`
for the architecture and per-component specifications.

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
│   └── run_tests.py           # Automated test runner (all 40 testcases)
│
├── testcase/                  # Test cases (test01–test40)
│   └── test0x/
│       ├── prompt.txt         # Turn-by-turn instructions
│       └── test0x.v           # Input Verilog netlist
│
├── tools/abc/                 # Berkeley ABC (clone separately)
├── main.py                    # System entry point
├── config.yaml                # Runtime configuration (model, API provider)
└── requirements.txt
```

## Setup

**1. Create virtual environment and install dependencies:**
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

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

## Usage

Pipe a prompt file into `main.py` to run a single testcase interactively:

```bash
cat testcase/test02/prompt.txt | python3 main.py -config config.yaml
```

Output is written to `testcase/test02/test02.log`.

## Running Tests

```bash
# Single testcase
python3 scripts/run_tests.py --case test02

# Range of testcases
python3 scripts/run_tests.py --range test01-test10

# All 40 testcases
python3 scripts/run_tests.py --all

# Debug mode (full LLM request/response logged)
python3 scripts/run_tests.py --case test02 --debug
```

Debug log is written to `testcase/test0x/test_run.log`.

## Output Files

| File | Description |
|------|-------------|
| `testcase/<case>/test_run.log` | Full debug log (only in `--debug` mode) |
| `testcase/<case>/<case>_out.v` | Output netlist written by the agent |
| `src/eda_engine/parser/parser_cpp` | Compiled C++ binary (not committed) |

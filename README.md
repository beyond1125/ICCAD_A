# CADA EDA Agent

The CADA EDA agent is an LLM-assisted tool designed for exploring and transforming gate-level Verilog netlists. It provides a natural-language interface for users to perform complex Electronic Design Automation (EDA) tasks such as path analysis, design depth calculation, and netlist modifications.

## Project Overview

The system leverages Large Language Models (LLMs) to interpret natural-language requests and translate them into specific EDA tool calls. These tools are executed against a custom C++ backend that performs efficient graph-based analysis on Verilog netlists.

Key features include:
- **Natural Language Interface**: Ask questions like "What is the max depth between in0 and out0?" or "How many paths exist between A and B avoiding C?"
- **Path Analysis**: Count paths and calculate combinational depths between nodes.
- **Netlist Exploration**: List nodes, get signal/gate info, and explore design structure.
- **Modifications**: Support for gate type replacement and Verilog design emission.

## Environment Requirements

- **Python**: 3.8 or higher.
- **C++ Compiler**: g++ supporting C++17 or later (required for regex and modern STL).
- **API Keys**: Access to OpenAI or Anthropic LLM services.

### Python Dependencies
Install the required packages using pip:
```bash
pip install -r requirements.txt
```
Primary packages include: `openai`, `anthropic`, `pyyaml`, and `python-dotenv`.

## Installation and Build Instructions

1. **Clone the Repository**
   ```bash
   git clone <repository_url>
   cd ICCAD_A
   ```

2. **Compile the C++ Parser**
   The EDA engine relies on a compiled C++ binary for netlist operations.
   ```bash
   g++ -std=c++17 parser/parser.cpp -o parser/parser_cpp.exe
   ```
   *Note: The Python engine expects the binary at `parser/parser_cpp.exe`.*

3. **Set Up Environment Variables**
   Copy the example environment file and add your API keys:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to include your `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.

4. **Configuration**
   Create or edit `config.yaml` (based on `config_example.yaml`) to set your preferred LLM provider and model.

## How to Run

There are two primary ways to run and test the system:

### 1. Live Mode (Real LLM API)
This mode connects to real LLM services (OpenAI or Anthropic) and uses the full power of the agent to handle arbitrary natural language requests.

**Prerequisites**: Valid API keys in `.env` or `config.yaml`.

**Execution**:
```bash
python main.py -config config.yaml
```
Once started, the agent will wait for input on `stdin`. You can initialize a testcase and then issue commands:
```text
This is the beginning of testcase my_test.
Load design design/netlist/test8.v
What is the logic depth from in0 to out3?
```

### 2. Dry-run Mode (Deterministic Stub)
This mode uses a rule-based `DeterministicLLMClient` to simulate LLM responses without making any real API calls. It is ideal for verifying the connectivity between the Python logic and the C++ parser.

**Execution**:
```bash
python tests/run_test.py
```
This script:
- Uses `tests/test_input.txt` as a simulated input stream.
- Patches the LLM client with a deterministic stub that recognizes keywords (load, depth, write).
- Verifies that the outputs (stdout and log files) match the expected format and values from the C++ parser.

## Directory Structure

- **`agent/`**: Contains the agentic logic, including the `Planner` which orchestrates the LLM loop and `tool_spec.py` which defines the available EDA tools.
- **`eda_engine/`**: The bridge between the Python agent and the C++ parser. `engine.py` handles process invocation and data marshaling.
- **`parser/`**: The C++ source code for the Verilog parser and graph-based netlist algorithms.
- **`design/netlist/`**: A directory for storing sample and target Verilog designs.
- **`tests/`**: Integration and regression tests, including the dry-run test environment.
- **`main.py`**: The main entry point for the application, handling CLI arguments and the top-level loop.
- **`io_manager.py`**: Manages the specific input/output formatting (#RESPONSE / #END tags) required for competition grading.

## Module Responsibilities and Interfaces

### Agent
The **Planner** drives the `LLM -> Tool-Call -> Result` loop. It maintains the conversation history and dispatches tool requests to the EDA Engine. It uses a **Tool Specification** to inform the LLM of the available operations.

### EDA Engine
The **EDAEngine** (located in `eda_engine/engine.py`) serves as a Python wrapper around the C++ CLI. It converts Python tool calls into shell commands executed against the compiled parser.

### Parser
The **C++ Parser** is the performance-critical component. It:
1. Parses gate-level Verilog into a directed graph representation.
2. Implements algorithms for `calculate_depth` and `count_paths`.
3. Handles structural modifications like `replace_gate`.
4. Emits updated designs back to Verilog format.

## Known Issues / TODO

- **Parser Scope**: The current C++ parser uses regex-based parsing optimized for flat, gate-level netlists. Complex behavioral Verilog or deeply nested hierarchies may not be fully supported.
- **Concurrency**: The current implementation processes one request at a time.

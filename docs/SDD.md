# [ICCAD Problem A] 系統設計文件（SDD）

## 1. 文件資訊

| 項目       | 內容             |
| -------- | -------------- |
| **版本**   | v0.2           |
| **建立日期** | 2026-06-10     |
| **最後更新** | 2026-06-10     |
| **撰寫者**  | CryingAtDesk   |
| **狀態**   | 草稿           |

### 版本歷程

| 版本   | 日期         | 修改人  | 修改內容摘要 |
| ---- | ---------- | ---- | ------ |
| v0.1 | 2026-06-10 | Riko | 初版建立   |
| v0.2 | 2026-06-10 | —    | 補充目錄結構、I/O 協議、已實作 Tool；對齊 log 路徑與系統名稱 |

### 相關文件

| 文件 | 用途 |
|------|------|
| [TSD.md](./TSD.md) | 未實作功能的技術細節（API、演算法） |
| [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) | SDD 規劃 vs 程式現況追蹤 |

---

## 2. 系統概述

### 2.1 系統背景與目標

**系統名稱**：`cada1066`

**系統簡述**：本系統為應對 2026 ICCAD Problem A 競賽所開發的「LLM 輔助網表探索與轉換系統」。系統需處理 40 個公開測試案例（public testcases），每個測試案例包含一連串由標準輸入（stdin）傳入的自然語言指令。系統必須透過 AI Agent 驅動自研的 EDA 引擎，對扁平化（flattened）的門級 Verilog 網表（gate-level Verilog netlist）進行精確的結構分析、邏輯轉換與優化驗證。

**設計目標**：

1. **電路支援度**：完整支援包含單一 Top 模組的扁平化電路。電路元件限定為 8 種基礎原語門（and, or, nand, nor, not, buf, xor, xnor，除 buf/not 為單輸入外，其餘皆為雙輸入一輸出）、標準 DFF（正緣觸發、非同步低電位重設）、常數（1'b1, 1'b0）及純量/總線型（scalar/bus）線網。

2. **確定性與正確性**：將自然語言精確轉譯為 EDA 核心操作，確保轉換後的網表滿足功能等價（Functional Equivalence）。

3. **自動化日誌記錄**：於標準輸出（stdout）及 `testcase/<case_name>/<case_name>.log` 檔案中，以 `#RESPONSE <id>` 與 `#END <id>` 標籤包裹每一步回應。

### 2.2 設計約束

| 約束類型 | 描述                                                           |
| ---- | ------------------------------------------------------------ |
| 時間限制 | 基本操作（read/write）60 秒，其他所有操作 300 秒                           |
| 指定模型 | `gpt-4o-mini`, `claude-haiku-4-5`                            |
| 效能約束 | LLM 呼叫參數固定為 `temperature: 0.2`，`max_output_tokens: 4096`。    |
| 輸出規範 | 必須輸出符合純淨 gate-level Verilog 檔案；回應內容嚴禁提及任何與評分、裁判或評估程序相關的關鍵字。 |

---

## 3. 系統架構

### 3.1 系統架構圖（System Architecture Diagram）

```
                    ┌────────────────────────┐
                    │      Contest Stdin     │ (Natural Language Request)
                    └───────────┬────────────┘
                                │
  ┌─────────────────────────────▼──────────────────────────────┐
  │ 1. AI Agent Front-End (前級代理)                            │
  │                                                            │
  │   ┌─────────────────┐  Prompt/Schema  ┌────────────────┐   │
  │   │  Prompt Manager │────────────────>│  External LLM  │   │
  │   │ (注入 EDA Spec) │<────────────────│  Cloud Service │   │
  │   └─────────────────┘  Tool Calls    └────────────────┘   │
  └─────────────────────────────┬──────────────────────────────┘
                                │
                                │ Translate into EDA Actions
                                ▼
  ┌────────────────────────────────────────────────────────────┐
  │ 2. EDA Tool Back-End (後端引擎)                             │
  │                                                            │
  │   ┌────────────────────────────────────────────────────┐   │
  │   │ Graph Engine (Netlist Parser / Graph Database)     │   │
  │   │ ├─ Verilog Reader/Writer                           │   │
  │   │ └─ Graph Traversal (深度計算、路徑追蹤)              │   │
  │   └─────────────────────────┬──────────────────────────┘   │
  │                             │                              │
  │                             ▼                              │
  │   ┌────────────────────────────────────────────────────┐   │
  │   │ Transformation & Formal Verification               │   │
  │   │ ├─ Logic Optimizer (原語替換、結構平衡)               │   │
  │   │ └─ Equivalence Checker (確保功能等價不變)             │   │
  │   └─────────────────────────┬──────────────────────────┘   │
  └─────────────────────────────│──────────────────────────────┘
                                │
                                ▼ Formatted Response Logs
                    ┌────────────────────────┐
                    │     Contest Stdout     │
                    │ & testcase/<case>.log    │
                    └────────────────────────┘
```

> **目前實作階段**：前級 Agent 與 Graph Engine 基礎能力已可運作；Transformation 僅部分實作；Formal Verification 尚未接入。詳見 [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md)。

### 3.2 目前實作架構（As-Built）

競賽評測以 stdin/stdout 驅動。目前實作採 **LLM Function Calling** 直接驅動 C++ Parser CLI，而非獨立的 JSON Execution Plan 層。

```
stdin → main.py → IOManager / Planner → LLMClient (OpenAI | Anthropic)
                              ↓ tool calls
                         EDAEngine (Python)
                              ↓ subprocess
                         parser_cpp (C++, src/eda_engine/parser/)
                              ↓
stdout + testcase/<case>/<case>.log
```

---

## 4. 模組劃分（Module Decomposition）

### 4.1 模組清單

| 模組編號  | 模組名稱               | 職責描述                                                                                                       |
| ----- | ------------------ | ---------------------------------------------------------------------------------------------------------- |
| M-001 | Agent 核心控制模組       | 處理 Stdin 輸入、維護對話狀態、解析 YAML 設定檔、與外部雲端 LLM 連線。                                                               |
| M-002 | Prompt 與 Schema 模組 | 將內部的 EDA 介面能力封裝為 Prompt Schema 餵給 LLM，引導其生成結構化的執行計畫。                                                       |
| M-003 | Netlist 解析與圖形模組    | 負責讀寫 Verilog（Read/Write），建立內部的圖形結構（Graph Representation），進行電路深度、路徑追蹤、時脈域（Clock Domain）與邏輯錐（Logic Cone）分析。 |
| M-004 | 網表轉換與優化模組          | 實作緩衝器插入（Buffer Insertion）、門級替換（Gate Replacement）、邏輯錐重構與懸空線網（Dangling nets）消除。                              |
| M-005 | 形式驗證與容錯模組          | 在優化前後進行功能等價性檢查（Equivalence Check），並在 LLM 出錯時提供反例（Counterexample）回饋。                                        |

### 4.2 模組依賴關係

```
M-001 (Agent核心) ─── 呼叫 ───> M-002 (Prompt管理) ───> 外部雲端 LLM API
 │
 └─── 驅動 ───> M-003 (Netlist圖形解析)
 │                  ▲
 │                  │ 讀取/修改圖形
 └─── 驅動 ───> M-004 (網表轉換與優化)
                    ▲
                    │ 調用驗證
               M-005 (形式驗證與容錯)
```

### 4.3 模組 ↔ 原始碼對照（目前已實作）

| 模組 | 原始碼路徑 | 說明 |
|------|------------|------|
| M-001 | `main.py` | 競賽入口、stdin loop、testcase init |
| M-001 | `src/agent/planner.py` | LLM tool-calling 迴圈、session 狀態注入 |
| M-001 | `src/agent/llm_client.py` | OpenAI / Anthropic 適配 |
| M-001 | `src/utils/config.py` | YAML + `.env` 設定載入 |
| M-001 | `src/utils/io_manager.py` | `#RESPONSE` / `#END` 與 log 寫入 |
| M-002 | `src/agent/tool_spec.py` | 暴露給 LLM 的 Tool Schema |
| M-002 | `src/agent/planner.py` (`_SYSTEM_PROMPT`) | System prompt 與 EDA 行為約束 |
| M-003 | `src/eda_engine/engine.py` | Python → C++ subprocess 橋接 |
| M-003 | `src/eda_engine/parser/` | C++ Verilog 解析、Graph、分析演算法 |
| M-004 | `src/eda_engine/parser/`（`replace_gate`） | 目前僅 gate type 替換 |
| M-005 | — | 尚未實作 |

---

## 5. 專案目錄結構（Repository Layout）

```
ICCAD_A/
├── .github/workflows/         # GitHub Actions CI
├── src/                       # 核心原始碼
│   ├── agent/                 # M-001, M-002
│   ├── eda_engine/            # M-003, M-004（部分）
│   │   └── parser/            # C++ 核心（parser.cpp / parser.hpp）
│   └── utils/                 # config, io_manager, paths
├── tests/
│   ├── unit_tests/            # 元件測試
│   └── integration_tests/     # 模擬 main loop 的整合測試
├── testcase/                  # 官方測資（保持根目錄，方便掛載）
├── docs/                      # SDD, TSD, IMPLEMENTATION_STATUS
├── scripts/
│   └── build_parser.py        # 跨平台編譯 C++ parser
├── tools/abc/                 # 外部 ABC 工具（選用，需自行 clone）
├── config.yaml                # LLM 執行設定
├── docker-compose.yml         # 容器化開發環境
├── Dockerfile
├── main.py                    # 系統入口（cada1066）
├── requirements.txt
└── README.md
```

**編譯產物（不納入版控）**：

- Linux/macOS：`src/eda_engine/parser/parser_cpp`
- Windows：`src/eda_engine/parser/parser_cpp.exe`

---

## 6. 執行與 I/O 協議（已實作）

### 6.1 啟動方式

```bash
python main.py -config <config_file_path>
```

程式內部識別名稱（`argparse` prog）：`cada1066`

### 6.2 輸入協議

- 從 **stdin** 逐行讀取自然語言指令。
- 若該行為 testcase 初始化訊息（含 `beginning of testcase` 或 `case name is`），則：
  1. 解析 `<case_name>`
  2. 重置 EDA engine 與 response 計數器
  3. 開啟 log 檔 `testcase/<case_name>/<case_name>.log`
  4. 產生 **Response 1**（初始化確認，不經 LLM）
- 其餘每行為一般 EDA 請求，交由 Planner 處理。

### 6.3 輸出協議

每一則回應（含 init 確認）格式如下：

```text
#RESPONSE <id>
<自然語言或技術回答內容>
#END <id>
```

- `<id>` 由 1 起算，在同一 testcase 內單調遞增。
- 同一內容同時寫入 **stdout** 與 **log 檔**。
- 寫入 `#END` 後立即 `flush` stdout（評測器依此送下一條指令）。

### 6.4 Log 與輸出檔案路徑

| 類型 | 路徑 | 說明 |
|------|------|------|
| 對話 log | `testcase/<case_name>/<case_name>.log` | 與 stdout 內容相同 |
| 輸出 netlist | `testcase/<case_name>/<case_name>_out.v` | `write_design` 產物（由 Agent 決定檔名） |
| Parser 錯誤 | `parser_error.log`（專案根目錄） | C++ parser 執行期錯誤 |

### 6.5 Session 狀態（目前已實作）

- **EDA Engine**：在同一 testcase 內保留已載入的 netlist（`load_design` 後可接續 `write_design` / 分析）。
- **LLM 對話**：每條 stdin 指令為獨立 LLM 請求；system prompt 會注入目前是否已 load design 及檔案路徑。
- **testcase 切換**：收到 init 訊息時呼叫 `planner.reset()` 清空 engine。

### 6.6 設定檔

`config.yaml` 支援：

- `provider`: `"openai"` | `"anthropic"`
- 各 provider 的 `api_key`（可寫 `${ENV_VAR}`）、`model`
- `generation.temperature`、`generation.max_output_tokens`

API 金鑰建議放在根目錄 `.env`（已被 gitignore）。

---

## 7. 已暴露 Tool 清單（Phase 1）

以下 Tool 已定義於 `src/agent/tool_spec.py`，由 Planner dispatch 至 `EDAEngine` → C++ parser。

| Tool | 說明 | C++ action |
|------|------|------------|
| `load_design` | 載入 Verilog 網表 | `load` |
| `write_design` | 寫出目前 netlist | `write` |
| `analyze_depth` | 兩節點間最大組合深度 | `calc_depth` |
| `find_paths` | 兩節點間路徑數（可避開某 node） | `count_paths` |
| `get_node_info` | 查詢 signal/gate 結構 | `get_info` |
| `list_nodes` | 列出所有節點 | `list_nodes` |
| `count_gates` | 依 gate type 計數 | `count_gates` |
| `replace_gate` | 替換指定 gate 的 type | `replace_gate` |

---

## 8. 建置、測試與 CI/CD（已實作）

### 8.1 環境建置

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python scripts/build_parser.py
```

### 8.2 測試

| 測試 | 路徑 | 說明 |
|------|------|------|
| 整合測試 | `tests/integration_tests/run_test.py` | 模擬 stdin loop（Deterministic LLM stub） |
| 元件測試 | `tests/unit_tests/verify_integration.py` | 直接呼叫 EDAEngine |

### 8.3 CI

GitHub Actions：`.github/workflows/ci.yml`

- 安裝依賴 → 編譯 parser → 執行 integration test

### 8.4 容器化（選用）

- `Dockerfile`：Python + g++ + 編譯 parser
- `docker-compose.yml`：掛載原始碼執行 `main.py`

---

## 9. 目標能力與實作差距

SDD §4 中 M-004（完整 transform）、M-005（形式驗證）、M-003 進階分析（clock domain、logic cone、完整 path 枚舉）等 **尚未完成**。

請參考：

- [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) — 模組 / Tool / 約束的完成度追蹤
- [TSD.md](./TSD.md) — 待實作功能的技術規格（開發前撰寫）

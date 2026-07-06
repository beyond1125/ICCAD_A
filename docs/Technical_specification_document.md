## 1. 文件資訊

| 項目       | 內容                          |
| -------- | --------------------------- |
| **文件編號** | TSD-CADA1066-CORE-001       |
| **版本**   | v1.0                        |
| **建立日期** | 2026-07-06                  |
| **最後更新** | 2026-07-06                  |
| **撰寫者**  | cada1066 團隊                 |


### 版本歷程

|版本|日期|修改人|修改內容摘要|
|---|---|---|---|
|v1.0|2026-07-06|cada1066 團隊|依程式碼現況重寫全文|

### 關聯文件

| 文件名稱                        | 文件編號                    | 版本   | 關聯性                      |
| --------------------------- | ------------------------ | ---- | ------------------------ |
| System_design_document.md   | SDD-CADA1066-001         | -    | 系統架構與模組劃分之上層設計文件         |
| OPEN_QUESTIONS.md            | -                        | -    | 規格模糊處之決策記錄，影響轉換語意實作細節    |
| REPORT_transform.md          | -                        | -    | 轉換工具、測試案例與演算法對照報告        |
| EVAL_HARNESS.md              | -                        | -    | 無金標評估工具鏈設計說明             |
| A_20260212.pdf               | -                        | -    | ICCAD 2026 Problem A 競賽規格 |

---

## 2. 技術概述

### 2.1 模組/功能範圍

> 本 TSD 涵蓋整個 cada1066 系統：LLM agent（工具呼叫迴圈與防幻覺機制）、C++ 網表引擎（Verilog 剖析、圖論分析與結構轉換）、以及評估工具鏈（四層評分/檢查腳本）。

**模組名稱**：cada1066（ICCAD 2026 Problem A 參賽系統）
**功能範圍**：

- LLM 代理人（`src/agent/`）：以 41 個結構化工具驅動 LLM，逐行讀取 stdin 請求，依 `#RESPONSE <id>` / `#END <id>` 協定輸出，並具備防幻覺三閘門（write gate、zero-tool gate、transform gate）與 context 收縮機制。
- C++ 網表引擎（`src/eda_engine/parser/`）：以指標鄰接表表示閘級網表，提供 Verilog 剖析/輸出、拓撲排序、深度與路徑分析、緩衝樹插入、基底重映射、結構化簡（懸空掃除、重複合併、反閘收合、常數傳播）、BLIF 匯出入（正反器切割模型）等 30 餘種 CLI action。
- 等價性驗證與深度最佳化：透過 Berkeley ABC 的 `cec`（形式等價驗證）與 `resyn2`/`balance`（深度最佳化）子行程。
- 評估工具鏈（`scripts/`）：協定完成度檢查、硬性需求檢查、無金標目標導向指標、分析類回答正確性裁決，共四層。

**不包含**：

- LLM 供應商（OpenAI、Anthropic）內部模型實作與 API 服務可用性。
- Berkeley ABC 內部演算法實作（`cec`、`resyn2`、`balance`、`sat` 等子指令的內部邏輯視為黑盒工具）。

### 2.2 技術環境

| 項目       | 規格                                                              |
| -------- | --------------------------------------------------------------- |
| 程式語言（代理人層） | Python 3.11                                                      |
| 程式語言（引擎層） | C++17（`g++` 或 `clang++`，經 `$CXX` 環境變數或自動偵測選用）                     |
| 形式驗證/最佳化工具 | Berkeley ABC（`cec`、`resyn2`/`balance`、`sat`），獨立 clone + make 建置    |
| 開發作業系統   | Linux（共用開發機，無 docker group 權限）                                    |
| 容器化環境    | Docker，基底映像 `python:3.11-slim`，多階段建置（見第 9 節）                       |
| 版本控制     | Git（`main` 為保護分支，開發於 feature/fix 分支，經 PR 合併）                       |

### 2.3 相依套件

| 套件名稱             | 版本         | 用途                              | 授權              |
| ---------------- | ---------- | ------------------------------- | --------------- |
| `openai`          | >=1.30.0   | OpenAI（gpt-4o-mini）API 用戶端 SDK   | Apache-2.0       |
| `anthropic`       | >=0.28.0   | Anthropic（claude-haiku-4-5）API 用戶端 SDK | Apache-2.0 |
| `pyyaml`          | >=6.0      | 解析 `config.yaml`                | MIT              |
| `python-dotenv`   | >=1.0.0    | 載入 `.env` 中的 API key 至環境變數       | BSD-3-Clause     |

`requirements.txt` 僅列出上述四項套件（未見其他相依項）。Berkeley ABC 與 C++17 編譯器（`g++`/`clang++`）為外部工具/系統相依，非 Python 套件，不受此表管理。

---

## 3. 類別與函式設計（Class & Function Design）

### 3.1 類別圖（Class Diagram）

系統橫跨兩個執行環境：Python 層（LLM 代理人與工具排程）與 C++ 層（`parser_cpp` 獨立二進位，透過 subprocess 呼叫）。兩者以「每次 action 一個子行程」的邊界溝通，無共享記憶體、無常駐 IPC。

```
                         Python 進程（main.py 主迴圈存活期間常駐）
┌───────────────────────────────────────────────────────────────────────┐
│  Config                    IOManager                                  │
│  ├─ provider / model       ├─ extract_testcase_name()                 │
│  ├─ ${ENV_VAR} 展開         ├─ init_testcase()  (雙 log sink)           │
│  └─ from_yaml()            └─ write_response()  (#RESPONSE/#END 協定) │
│         │                          ▲                                  │
│         ▼                          │                                  │
│  ┌─────────────────────────────────┴────────────────────┐             │
│  │                      Planner                          │             │
│  │  - _dispatch: Dict[str, Callable]  (41 個工具→engine)   │             │
│  │  - _conversation_history                               │             │
│  │  - 三道防幻覺 gate（write / zero-tool / transform）       │             │
│  │  - context 收縮（主動 + 反應式）                          │             │
│  │  + process(user_request) -> str                        │             │
│  │  + reset()                                             │             │
│  └───────────────┬─────────────────────────┬──────────────┘             │
│                  │ chat()                  │ dispatch 呼叫              │
│                  ▼                         ▼                          │
│  ┌───────────────────────────┐   ┌─────────────────────────────────┐   │
│  │       LLMClient           │   │           EDAEngine             │   │
│  │  - provider 路由            │   │  - _loaded_filepath             │   │
│  │  - retry (2,8,20s / 4 次)  │   │  - _original_filepath           │   │
│  │  - _record_usage()         │   │  - _session_dir (tempfile)      │   │
│  │  + chat(messages)          │   │  - verified_writes              │   │
│  └───────────────┬────────────┘   │  + load_design/write_design     │   │
│                  │                │  + analyze_*  (唯讀)             │   │
│                  ▼                │  + insert_buffers/reduce_depth/…│   │
│         [OpenAI / Anthropic API]  │    (transform，17 種)            │   │
│                                   │  + check_equivalence             │   │
│                                   └───────────────┬─────────────────┘   │
└───────────────────────────────────────────────────┼─────────────────────┘
                                                     │ subprocess.run(
                                                     │   [parser_cpp, --in, ...,
                                                     │    --action, ...], timeout=150)
                                                     │ 或 ABC (cec / resyn2, timeout=180)
                    ══════════════════ 行程邊界（每次呼叫全新子行程）══════════════════
                                                     ▼
                         C++ 進程（parser_cpp，單次 action 執行後即結束）
┌───────────────────────────────────────────────────────────────────────┐
│  main.cpp（CLI 引數解析 + action 分派，280 行）                            │
│         │                                                              │
│         ▼                                                              │
│  ┌─────────────────────────┐        ┌───────────────────────────┐      │
│  │      VerilogParser       │        │      VerilogWriter         │      │
│  │  （無狀態，static regex）  │        │  （全靜態方法）              │      │
│  │  + parse(file) -> Graph  │        │  + write_verilog(Graph)    │      │
│  └────────────┬─────────────┘        └──────────────┬──────────────┘     │
│               ▼                                      │                  │
│  ┌────────────────────────────────────────────────────▼──────────────┐  │
│  │                              Graph                                 │  │
│  │  - nodes: unordered_map<string, Node*>  (名稱查找表，非擁有)          │  │
│  │  - all_nodes: vector<Node*>             (唯一擁有權容器)              │  │
│  │  - topological_order: vector<Node*>     (快取，見第 5 節風險)         │  │
│  │  + compute_topological_sort() / compute_levels() / get_critical_path│  │
│  │  + count_paths() / find_all_paths()                                │  │
│  │  + insert_buffers() / remap_cone_to_basis() / decompose_in_cone()   │  │
│  │  + sweep_dangling() / merge_duplicate_gates() / collapse_inverters()│  │
│  │  + const_propagate() / write_blif() / load_logic_blif()            │  │
│  └────────────────────────────────┬────────────────────────────────────┘  │
│                                   │ 擁有                                  │
│                                   ▼                                      │
│                          ┌──────────────────┐                            │
│                          │       Node        │  裸指標鄰接表               │
│                          │  - name/type      │  inputs/outputs：           │
│                          │  - gate_type      │  vector<Node*>（不擁有）     │
│                          │  - inputs/outputs │                            │
│                          │  - pin_conns      │  控制腳（CK/RN/SN）獨立存放   │
│                          └──────────────────┘                            │
└───────────────────────────────────────────────────────────────────────┘
```

### 3.2 類別詳細設計（Python 側）

| 類別 | 檔案 | 關鍵欄位 | 職責 |
|---|---|---|---|
| `Config` | `src/utils/config.py` | `provider`, `openai`, `anthropic`, `generation` | YAML 解析、`${ENV_VAR}` 展開、`.env` 載入 |
| `IOManager` | `src/utils/io_manager.py` | `case_name`, `response_id`, `_log_files`（雙 sink） | stdin 逐行協定輸出、`#RESPONSE`/`#END` 格式化、CWD 與 testcase 目錄雙份 log |
| `LLMClient` | `src/agent/llm_client.py` | `prompt_tokens`/`completion_tokens`/`total_tokens`/`api_calls` | 供應商路由（OpenAI/Anthropic）、格式轉換、重試退避、token 記帳 |
| `Planner` | `src/agent/planner.py` | `_dispatch`（41 工具對映）、`_conversation_history` | agentic loop、三道防幻覺 gate、context 收縮、修正上限 |
| `EDAEngine` | `src/eda_engine/engine.py` | `_loaded_filepath`, `_original_filepath`, `_session_dir`, `verified_writes`, `_max_fanout_constraint` | 41 個工具方法的實作、session 檔案鏈接、ABC 子行程呼叫、磁碟驗證寫入 |

### 3.3 方法規格（節選，完整工具清單見 3.4 節）

| 方法 | 簽名 | 語意重點 |
|---|---|---|
| `Planner.process` | `(user_request: str) -> str` | 單次請求完整 agentic loop（最多 10 輪 LLM↔工具往返），回傳最終回覆文字 |
| `Planner._execute_tool` | `(tc: ToolCall) -> str` | 派工至 `_dispatch`；捕捉未知工具名、`TypeError`（幻覺參數）、一般例外，全部轉為可讀錯誤字串餵回 LLM |
| `LLMClient.chat` | `(messages) -> LLMResponse` | provider-agnostic 入口，最多 4 次嘗試（延遲 0/2/8/20 秒，即首次加 3 次重試）與致命錯誤即時上拋 |
| `EDAEngine.write_design` | `(filepath: str) -> str` | 呼叫 parser `write` action 後，以 `os.path.isfile` 二次驗證磁碟寫入，不信任 parser 自報成功 |
| `EDAEngine.check_equivalence` | `(reference: Optional[str] = None) -> str` | 雙方各自匯出 flop-cut BLIF，交由 ABC `cec` 驗證，預設參照 `_original_filepath` |
| `Graph::compute_topological_sort` | `() -> void`（C++） | Kahn 演算法，DFF 輸出邊視為切斷點，快取進 `topological_order` |
| `Graph::write_blif` | `(const std::string& filename) -> void`（C++） | 正反器切割模型：DFF Q→`.inputs`，D→`.outputs`（`__D_<inst>`） |

### 3.4 工具面規格（LLM 可呼叫之 41 個工具）

`tool_spec.py` 的 `EDA_TOOLS` 共 41 個工具定義，與 `Planner._dispatch` 完全一一對應。

**IO 類（2）**

| 工具 | 參數 | engine 方法 |
|---|---|---|
| `load_design` | `filepath` | `load_design` |
| `write_design` | `filepath` | `write_design`（磁碟驗證寫入） |

**ANALYSIS 類（21，唯讀，不改變 `_loaded_filepath`）**

| 工具 | 參數 |
|---|---|
| `analyze_depth` | `start_node?`, `end_node` |
| `analyze_critical_path` | `start_node`, `end_node` |
| `find_paths` | `start_node`, `end_node`, `avoid_node?` |
| `count_gates` | — |
| `count_fanin_gates` / `count_fanout_gates` | `node_name` |
| `get_fanin_cone` / `get_fanout_cone` | `node_name` |
| `count_gates_in_cone` | `node_name`, `direction?` |
| `get_fanin_depth` | `node_name` |
| `get_node_info` | `node_name` |
| `list_gates_by_type` | `gate_type` |
| `flipflops_by_clock` | `clock` |
| `max_pi_to_dff_depth` / `list_floating` / `highest_fanout_pi` / `list_nodes` / `list_pio` / `r2r_paths` / `deepest_cone_output` | — |
| `signal_depends_on` | `target`, `source` |

**TRANSFORM 類（17，改變 `_loaded_filepath` 指向；同集合即 `Planner._TRANSFORM_TOOLS`）**

| 工具 | 參數 |
|---|---|
| `replace_gate` | `target`, `new_type`, `out_file?` |
| `insert_buffers` | `max_fanout` |
| `insert_dedicated_buffers` | `signal` |
| `buffer_signal` | `signal`, `max_fanout` |
| `reconnect_pin` | `gate`, `pin`, `signal` |
| `reduce_depth` / `remove_dangling` / `collapse_inverters` / `merge_equivalent_gates` | — |
| `rename_node` | `old_name`, `new_name` |
| `decompose_gates_in_cone` | `cone_root`, `gate_type`, `target_basis` |
| `decompose_all_gates` | `gate_type`, `target_basis` |
| `convert_cone_to_basis` | `cone_root`, `target_basis` |
| `reconstruct_netlist_to_basis` | `target_basis` |
| `restructure_to_depth` | `node`, `target_depth` |
| `optimize_outputs_to_depth` | `max_depth` |
| `const_propagate` | `mode?`, `gate_type?`, `const_value?` |

**VERIFY 類（1）**

| 工具 | 參數 |
|---|---|
| `check_equivalence` | `reference?`（預設比對 `_original_filepath`） |

**通用攔截層**：任何工具輸出經 `Planner._truncate_large_result` 過濾——超過
12000 字元（約 3000 token）的結果落地為 `<tool_name>_<arg_tag>.log`（存於已載
入設計同目錄），回傳含 `notice`/`saved_to_file`/樣本欄位的 JSON 摘要；system
prompt 要求 LLM 在回覆中提及 `saved_to_file` 路徑。

---

## 4. 演算法邏輯（Algorithm Design）

### 4.1 演算法清單

| 名稱 | 位置 | 複雜度 | 用途 |
|---|---|---|---|
| Verilog 剖析（正則管線 + static regex 提升） | `verilog_parser.cpp:7-226` | O(檔案大小)，正則掃描與敘述長度成正比 | 將閘級 Verilog 轉為 `Graph` |
| Kahn 拓撲排序（DFF 切斷） | `graph.cpp:31-61` | O(V+E) | 把時序電路切成純組合 DAG 供分析使用 |
| 層級化深度計算 | `graph.cpp:63-137` | O(V+E) | 逐節點層級（`calc_depth`/`analyze_depth` 基礎） |
| 關鍵路徑貪婪回溯 | `graph.cpp:139-173` | O(V+E) + O(路徑長度×平均扇入) | 由層級值反向挑選最大前驅重建關鍵路徑 |
| 路徑計數 DP | `graph.cpp:175-200` | O(V+E) | 沿拓撲序累加路徑數，不枚舉路徑本身 |
| 路徑枚舉 DFS（目標可達性剪枝 + 上限） | `graph.cpp` `find_all_paths` | O(V+E) 反向 BFS + O(路徑數×路徑長)，收集上限 10000 條 | 枚舉 start→end 路徑；先以反向 BFS 標記可達目標的子圖再 DFS，超過上限時輸出附註 DP 精確總數；顯示截斷於 100 條 |
| 緩衝樹插入（平衡分批） | `graph.cpp:513-623` | O(扇出數)（樹狀分層近似 O(n log n)） | 限制扇出，含控制腳（pin_conn）扇出再加強 |
| 基底重映射（布林恆等式 + 反閘共用） | `graph.cpp:1224-1306` | O(cone 大小) | 全域/錐狀邏輯轉換為 `nor_not`/`and_not`/`nand_not` 基底 |
| XOR→4-NAND 分解 | `graph.cpp:682-746`（`decompose_in_cone`） | O(1) 每閘 | 點狀單一閘型別到目標基底的精確結構轉換 |
| 懸空掃除（反向可達性） | `graph.cpp:646-668` | O(V+E) | 以 PO/DFF 為種子反向 DFS，移除不貢獻輸出的閘 |
| 結構重複合併（雜湊簽章 + 定點） | `graph.cpp:889-936` | 每輪 O(V·平均扇入)，輪數上界 O(V) | 合併計算相同函式的重複閘 |
| 反閘收合（定點） | `graph.cpp:1174-1216` | O(V·L)，L 為反閘鏈長 | 收合 `NOT(NOT(x))` 背對背模式 |
| 常數傳播 | `graph.cpp:940-1169` | O(V+E) 每輪，定點迭代 | 沿常數輸入化簡邏輯閘 |
| BLIF 匯出（flop-cut） | `graph.cpp:436-508` | O(V+E) + O(2^k) XOR/XNOR（k 通常=2） | 產生供 ABC 使用的正反器切割組合邏輯 |
| BLIF 匯入（真值表查表） | `graph.cpp:330-434` | O(2^nin) 每 `.names` 區塊 | 將 ABC 最佳化後的 BLIF 還原為 `Graph` 原生閘 |
| 防幻覺三閘門 | `planner.py:269-304` | O(1) 判斷 | write/zero-tool/transform 三道 gate，修正上限 2 次 |
| context 收縮（主動 + 反應式） | `planner.py:238-325` | O(對話歷史長度) | 主動於呼叫前檢查字元預算；反應式於「prompt too long」例外時強制收縮重試 |
| LLM 重試退避 | `llm_client.py:93-121` | O(1)（最多 4 次嘗試） | 暫時性供應商錯誤指數退避重試，致命錯誤即時上拋 |

### 4.2 演算法詳述（六項最關鍵機制）

**(1) BLIF 匯出：正反器切割模型（flop-cut，`write_blif`，`graph.cpp:436-508`）**
把時序電路轉為 ABC 可驗證的純組合邏輯：每個 DFF 的 Q 輸出網路變成 BLIF 的 `.inputs`（代表「上一狀態」），每個 DFF 的 D 輸入映射到新的 `.outputs` 項 `__D_<inst>`（代表「下一狀態」）。若某 PO net 恰好也是某 DFF 的 Q net，該 PO 從 `.outputs` 省略（BLIF 不允許同一 net 既是 input 又是 output，且等價性已由對應 `__D_<inst>` 覆蓋）。同一 net 被多個 DFF 共同驅動時輸入端僅發一次（`emitted_in` 去重），但每個 flop 各自產生獨立的 `__D_<inst>` tap。此模型僅對「保留正反器邊界」的轉換（緩衝、深度最佳化、掃除、重新命名、分解、基底重映射、反閘收合）為健全（sound）；任何新增/刪除/合併正反器的轉換會使 flop-cut `cec` 誤判為不等價（見 `docs/OPEN_QUESTIONS.md` D6）。

**(2) 路徑枚舉 DFS 對比路徑計數 DP（`find_all_paths` vs `count_paths`）**
兩者解決不同問題但常被混淆：`count_paths` 是標準 DAG 上的動態規劃——沿拓撲序做 `path_count[v] += path_count[u]`，時間複雜度 O(V+E)，與路徑實際數量無關，不會指數爆炸。`find_all_paths` 是真正的遞迴枚舉（DFS with backtracking），2026-07-06 起帶兩層防護：**目標可達性剪枝**（枚舉前先自終點做一次反向 BFS 標記「能到達終點」的子圖，DFS 只在該子圖內下降——沒有剪枝時 DFS 會在到不了終點的死路子圖裡指數級遊走，test12 的實測案例即因此耗盡 150 秒逾時，剪枝後同一查詢 8 秒內完成且實際只有 8 條路徑）與**收集上限 10000 條**（達上限時輸出首行附註以 `count_paths` DP 算出的精確總數，供呼叫端取得真實數字）。顯示階段仍另有 100 條的截斷。歷史對照：`r2r_paths` 從一開始就有 `MAX_PATHS_PER_PAIR=5`／`MAX_TOTAL_PATHS=200` 的生成階段上限，是本次修法的參照設計。

**(3) 基底重映射（`remap_cone_to_basis`，`graph.cpp:1224-1306`）**
以布林恆等式將任意邏輯閘轉換為三種目標基底之一，並用 `inv_cache`（`unordered_map<Node*, Node*>`）快取每個訊號的反相結果以**共用反閘**、避免重複生成：
- `nor_not`：AND(a,b)=NOR(!a,!b)；OR(a,b)=NOT(NOR(a,b))；XOR 透過 NOR-NOR 展開的 XNOR 再反相。
- `and_not`：NOR(a,b)=AND(!a,!b)；XOR/XNOR 以雙重迪摩根展開組合。
- `nand_not`：AND(a,b)=NOT(NAND(a,b))；OR(a,b)=NAND(!a,!b)；**XOR 用標準 4-NAND 結構**：`n1=NAND(a,b); n2=NAND(a,n1); n3=NAND(b,n1); XOR=NAND(n2,n3)`。

若 `basis` 字串未匹配任一已知基底，回傳 `-1`，`main.cpp` 印出 `"Failure: unsupported basis 'B'."`。

**(4) 緩衝樹插入（平衡分批，`insert_buffers`/`insert_buffers_on_signal`/`insert_dedicated_buffers`，`graph.cpp:513-623`）**
對每個扇出超過 `max_fanout` 的閘輸出，把消費者清單分批（每批 `max_fanout` 個）各接一個新緩衝閘；若剩餘批數仍超過上限則遞迴分批，形成多層緩衝樹，直到最後一層批數 ≤ 上限為止。`insert_buffers_on_signal` 額外處理 **DFF 控制腳的扇出**——控制腳（CK/RN/SN）本無圖邊，改寫 `pin_conns[i].signal` 而非圖邊來重新接線。`insert_dedicated_buffers` 則是 1:1 buffer-per-load，不共用、不分層。三者複雜度皆 O(扇出數)。

**(5) 防幻覺三閘門（`Planner.process`，`planner.py:269-304`）**
針對小型模型常見的「回答已完成但實際未呼叫工具」問題設計三道 gate：
- **Write gate**：請求文字命中寫入意圖正則，但 `engine.verified_writes` 中無本輪新增且檔名相符的寫入紀錄 → 要求務必呼叫 `write_design`。
- **Zero-tool gate**：本輪完全沒呼叫任何工具就給答案 → 要求先呼叫工具再回答。
- **Transform gate**：請求非問句且命中轉換意圖正則，但執行過的工具集合與 17 種 transform 工具集合無交集 → 要求呼叫對應 transform 工具。
三個 gate 共用同一個 `corrections` 計數器，上限為 2 次；用盡後 write 請求直接回覆明確失敗訊息，其餘請求直接跳出迴圈保留當輪文字。

**(6) Context 收縮（主動 + 反應式，`planner.py:238-325`）**
**主動**：每輪呼叫 LLM 前檢查對話訊息總字元數是否超過 `_MAX_CONTEXT_CHARS=300_000`，超過則保留最近 `_KEEP_RECENT_TOOL_RESULTS=2` 筆完整工具結果，其餘壓縮/摘要。**反應式**：當 `chat()` 拋出的例外文字含 "prompt is too long" 時，以更激進參數（`keep_recent=1, limit=0`）強制收縮後 `continue` 重試同一輪，而非直接放棄。閾值刻意保守（遠低於 200k-token API 上限），因為 netlist 識別字元密度較一般文字高（約 2 字元/token）。

---

## 5. 資料結構（Data Structures）

**Node 指標鄰接表與所有權模型**：`Graph::all_nodes`（`std::vector<Node*>`）是唯一的所有權容器，插入順序即解析順序（決定 `list_nodes` 輸出順序）；`Graph::nodes`（`std::unordered_map<std::string, Node*>`）僅為名稱→節點的查找索引，不擁有記憶體。`Graph` 解構子遍歷 `all_nodes` 逐一 `delete`。每個 `Node` 自帶其鄰居的 **裸指標鄰接表**：`std::vector<Node*> inputs` / `outputs`，有向邊以雙向記錄（`from->outputs` 推入 `to`，同時 `to->inputs` 推入 `from`）。刪除節點的所有演算法（`sweep_dangling`、`merge_duplicate_gates`、`collapse_inverters`、`const_propagate`）遵循同一模式：先從 `all_nodes` 篩出 keep/drop 兩組、清理 keep 組中對 drop 節點的殘留指標、`nodes.erase()`、最後才 `delete`——先斷邊、後刪除，避免懸空指標。

**PinConn 與 DFF 控制腳分離儲存**：`std::vector<PinConn> pin_conns` 只有具名接腳（如 `.CK(clk)`）的閘（主要是 DFF）才會填入。`PinConn` 含 `pin`（接腳名）、`signal`（連線網路名，字串非指標）、`is_const`（訊號是否為常數字面值）、`edge_dir`（0=無圖邊對應的控制腳或常數，1=輸入邊，2=輸出邊）。控制腳（CK/RN/SN）僅存在 `pin_conns`，不建立圖邊；資料腳（D/Q）才同時建立 `inputs`/`outputs` 圖邊。這是「時序控制邊界」與「一般組合邏輯邊」在資料結構層級的分離機制。

**常數與 bit-select 的字串命名慣例**：程式碼中沒有獨立的「常數節點」或「bit-select 節點」類別，一律用字串命名慣例表示：常數以字面值本身作為節點名（如 `"1'b0"`），節點型別仍是 `NodeType::SIGNAL`；向量位元命名為 `"base[idx]"`（如 `"data[3]"`），由 `VerilogParser::expand_bus` 在解析階段展開成個別純量節點，圖本身不理解「向量」概念——向量僅是文字層面的巧合，`VerilogWriter::group_signals` 在輸出時以正則 `^(.+)\[(\d+)\]$` 反向偵測連續索引重組回 `[msb:lsb]` 形式。

**`topological_order` 快取（失效一致性已於 2026-07-06 修復）**：`Graph::topological_order` 是快取的拓撲排序結果，`compute_levels`/`count_paths` 僅在其為空時才重新計算。原本只有 `const_propagate` 會在改圖後清空快取（潛伏的失效不一致缺陷）；現在 `add_edge`（覆蓋所有新增邊的變更路徑）與三個節點刪除函式（`sweep_dangling`、`collapse_inverters`、`merge_duplicate_gates`）都會顯式呼叫 `topological_order.clear()`，單一行程內混合「變更圖 → 深度/路徑計算」的呼叫序列不再讀到過期排序。

**Python 側 session 檔案鏈**：`EDAEngine.__init__` 建立 `_loaded_filepath`（目前作用中的設計檔案，隨每次 transform 改變指向）、`_original_filepath`（原始檔案，永久保留供 `check_equivalence` 預設參照）、`_session_dir`（`tempfile.mkdtemp` 建立的本次 process 生命週期暫存目錄）。每個 transform 方法遵循同一模式：以 `_session_path(tag)` 產生唯一檔名、呼叫 parser action 寫出、成功則重新指向 `_loaded_filepath`，形成「原始檔 → session 檔案1 → session 檔案2 → ...」的鏈。

**`verified_writes`**：`write_design` 在 parser 回報 "Success" 後，額外以 `os.path.isfile(filepath)` 二次驗證磁碟寫入是否真實存在，通過才將絕對路徑加入 `self.verified_writes` 清單——這是 `Planner._write_satisfied`（write gate）判斷寫入是否完成的唯一資料來源，不信任 parser 自報成功。

---

## 6. 錯誤處理機制（Error Handling）

| 情境 | 處理方式 | 位置 |
|---|---|---|
| LLM 呼叫拋非致命例外（暫時性錯誤） | 依 `(2, 8, 20)` 秒延遲重試最多 4 次；全部失敗後上拋，`Planner.process` 捕捉：若含 "prompt is too long" 則強制收縮 context 並重試本輪一次，否則回傳 `Error communicating with the LLM service: ...` | `llm_client.py:93-121`；`planner.py:239-251` |
| LLM 呼叫拋致命例外（quota/認證/格式錯誤） | `_FATAL_MARKERS` 命中則立即上拋不重試，向上由 `Planner.process` 轉為 error 答案，行程不崩潰 | `llm_client.py:96-98, 118-119` |
| 工具執行拋一般例外 | `Planner._execute_tool` 捕捉並回傳 `Error executing '<tool>': <exc>` 字串餵回 LLM，不中斷主迴圈 | `planner.py:395-397` |
| 未知工具名稱（LLM 幻覺工具名） | `_dispatch.get(tc.name)` 為 `None` → 回傳含已知工具清單的錯誤字串 | `planner.py:374-381` |
| 幻覺參數（錯誤參數名稱） | 呼叫拋 `TypeError` → 回傳 `Error: tool '<name>' was called with invalid arguments ...` | `planner.py:389-394` |
| Parser subprocess 逾時 | 捕捉 `subprocess.TimeoutExpired`，回傳固定格式錯誤字串（註明 design state 未變） | `engine.py:107-108, 139-146` |
| Parser 二進位找不到 | 捕捉 `FileNotFoundError`，回傳明確錯誤；`health_check()` 於啟動期提前警告 | `engine.py:111-112, 150-151, 805-808` |
| ABC 二進位缺失 | `reduce_depth`/`check_equivalence` 前置檢查 `os.path.isfile`，缺失時回傳建議建置或設 `ABC_BIN` 的錯誤 | `engine.py:433-434, 769-773, 809-812` |
| 寫入失敗（parser 回報成功但檔案不存在） | `write_design` 二次驗證 `os.path.isfile`，不一致時回傳「reported success but no file exists」且不計入 `verified_writes` | `engine.py:335-340` |
| Config 讀取錯誤 | `main.py` 啟動期 `try/except` 後 `sys.exit`，直接終止行程（無法優雅降級） | `main.py:66-69` |
| 主請求迴圈頂層未預期例外 | 捕捉後記完整堆疊至 stderr，回應改為 `Internal error while processing request: ...`，但仍完成 `#RESPONSE`/`#END` 協定輸出，行程不崩潰、繼續讀下一行 stdin | `main.py:104-108` |
| C++ 側統一錯誤輸出 | `log_error` 同時寫 stderr 與附加寫入 `parser_error.log`（含時間戳），不主動終止程式 | `utils.cpp:23-32` |
| C++ 側檔案開啟失敗 | `VerilogParser::parse` 開啟失敗時 `log_error` 後直接 `return`，`graph` 保持空白，後續 action 仍執行但僅得空結果 | `verilog_parser.cpp:9-12` |
| C++ 側未知 action / 缺必要旗標 | `log_error` + `return 1`（有 exit code）；例外是 `count_gates_in_cone` 缺 `--node` 時直接印到 **stdout**（非 stderr），與其他 action 慣例不一致 | `main.cpp:275-277, 221` |
| C++ 側節點查找失敗 | 回傳字串內嵌 `"Error: ... not found."`，**非例外、不設 exit code**，`main.cpp` 一律 `return 0`；上層只能靠解析 stdout 字串判斷成功/失敗 | 見第 2 節 CLI 表 |

### 6.1 靜默失敗風險（2026-07-06 修復狀態）

- **`write`/`write_blif` 缺 `--out`**（已修復）：原本 `log_error` 後未 `return 1`，exit code 為 0 且無任何 stdout 輸出，外層只看 exit code 會誤判成功；現已補上 `return 1`。Python 層的 `verified_writes` 磁碟二次驗證仍保留作為縱深防禦。
- **BLIF 匯入 `nin>=3` 的 `.names` 區塊**（已修復為大聲失敗）：原本會落入 2-input 分支以前兩個輸入加超界 mask 建出**錯誤邏輯**；現在 `flush` 在真值表展開前即攔截（同時避免 O(2^nin) 展開），累計 `Graph::blif_unsupported`，`rebuild` action 偵測到即輸出 `"Failure: BLIF import contained N unsupported .names block(s)..."` 並 `return 1`。完整支援 3+ 輸入查表仍未實作（目前 ABC 腳本僅產 2-input AIG，無實際需求）。
- **`stoi` 無例外防護**（已修復於 CLI 層）：`main.cpp` 的數值旗標一律經 `int_flag()` 輔助函式解析，非數字值會 `log_error` 後乾淨地 `exit(1)`，不再因未捕捉例外 `terminate`。`verilog_parser.cpp` 的 range 解析因正則已保證僅匹配數字字元，維持原狀（超長數字的 `out_of_range` 理論上仍可能，實務風險低）。
- **`parser_error.log` 側寫**（現況維持）：所有 `log_error` 呼叫除寫 stderr 外，同時附加寫入執行目錄下的 `parser_error.log`（含時間戳）；此檔案持續累積、不自動清空，屬執行期產物而非版本控管內容。

---

## 7. 自動化測試規劃（Test Plan）

### 7.1 測試策略

現況為**誠實的最小可行狀態**：CI 只跑 1 個整合測試（以 deterministic LLM stub 取代真實 API，避免測試耗費 token 與受供應商可用性影響），單元測試腳本存在但無斷言（僅為手動煙霧測試）。真正的功能與品質保證主要落在**系統級評估工具鏈**（四層，見第 5 節工具面規格與 README）：協定完成度（`run_all_llm.py`）、硬性需求（`check_results.py`）、無金標目標導向指標（`eval_harness.py`）、分析類回答正確性（`check_answers.py` + `netlist_oracle.py`）。此外 `netlist_oracle.py --selftest` 與 `check_answers.py --selftest` 提供不依賴真實 testcase 資料的邏輯自我檢查進入點。

### 7.2 測試覆蓋率

| 測試類型 | 現況 | 目標（建議） |
| ------ | --------- | ----------------------- |
| 單元測試 | 近乎 0%（`tests/unit_tests/verify_integration.py` 僅列印結果，無斷言，未被 CI 引用） | 對 `EDAEngine` 各方法與 `Planner` 三道 gate 補上斷言式單元測試，逐步提升至 ≥ 50% 行覆蓋 |
| 整合測試 | 1 條路徑（CI 跑 `tests/integration_tests/run_test.py`，以 `DeterministicLLMClient` 取代真實 LLM，斷言 response id 序列、`#END`/`#RESPONSE` 對應、log 與 stdout 逐字元相等） | 擴充至覆蓋防幻覺三閘門各自觸發路徑、context 收縮觸發路徑 |
| 系統級測試 | 40/40 testcase 皆可透過四層評估工具鏈驗證（協定完成度 + 硬性需求 + 無金標指標 + 分析正確性） | 維持 40/40 全覆蓋，並持續補上 `docs/OPEN_QUESTIONS.md` 中標記為 ❓ 的分析工具 |

### 7.3 單元測試規格（現況）

- `tests/unit_tests/verify_integration.py`：非 pytest 風格、`if __name__ == "__main__"` 直接執行的手動驗證腳本。依序呼叫 `EDAEngine.load_design`/`list_nodes`/`get_node_info`/`analyze_depth`/`replace_gate`，僅 `print()` 結果，**無斷言、無 pass/fail 判定**，未被 CI 引用，屬於煙霧測試而非正式單元測試。

### 7.4 整合測試規格（現況）

- `tests/integration_tests/run_test.py` + `test_input.txt`：以 `DeterministicLLMClient`（規則式 stub）取代真實 LLM，透過 `mock.patch` 完整跑一次 `main.py` 主迴圈邏輯，斷言 response id 序列為 `[1,2,3,4]`、`#END` 與 `#RESPONSE` 一一對應、testcase-init 回覆措辭正確、`testcase/test8/test8.log` 內容與 stdout 逐字元相等。這是 `.github/workflows/ci.yml` 中唯一自動執行的測試步驟；CI 不建置 ABC、不跑 `check_results.py`/`eval_harness.py`/`check_answers.py`、不呼叫真實 LLM API。

---

## 8. 組態與環境設定

**`config.yaml` schema**：

```yaml
provider: "anthropic"        # "openai" | "anthropic"
openai:
  api_key: "${OPENAI_API_KEY}"
  model: "gpt-4o-mini"
anthropic:
  api_key: "${ANTHROPIC_API_KEY}"
  model: "claude-haiku-4-5"
generation:
  temperature: 0.2
  max_output_tokens: 4096
```

`Config.from_yaml`（`config.py:70-105`）解析上述 YAML，對每個字串值呼叫 `_expand()` 展開 `${ENV_VAR}` 佔位符。

**`${ENV_VAR}` 展開規則**：找不到對應環境變數時**保留原字串不變**（`_expand`，`config.py:38-42`：`os.environ.get(m.group(1), m.group(0))`），不拋錯、不留空字串。

**`.env` 載入（python-dotenv）**：`Config` 模組載入時即執行 `load_dotenv(PROJECT_ROOT / ".env", override=True)`（`config.py:29-33`）——`override=True` 代表 `.env` 內容會覆蓋既有環境變數；若 `python-dotenv` 未安裝則 `except ImportError: pass`，退回僅使用真實環境變數。

**`ABC_BIN`/`PARSER_BIN` 環境變數覆蓋**：`EDAEngine` 支援以環境變數覆蓋 ABC 與 `parser_cpp` 二進位的預設路徑，供非標準安裝位置或容器化部署時指向自訂路徑；缺失時 `health_check()` 於啟動期在 stderr 提前警告，`reduce_depth`/`check_equivalence` 呼叫前也各自檢查檔案是否存在。

---

## 9. 建置與部署

### 9.1 建置指令

```bash
# 1. 編譯 C++ 網表引擎（輸出 src/eda_engine/parser/parser_cpp）
python3 scripts/build_parser.py

# 2. 建置 Berkeley ABC（獨立 clone，非本專案原始碼一部分）
cd tools && git clone https://github.com/berkeley-abc/abc.git
cd abc && make ABC_USE_NO_READLINE=1 abc

# 3. Docker 映像建置（多階段，見 9.2）
docker build -t cada1066 .

# 4. 執行（競賽入口點）
./cada1066_alpha -config config.yaml
```

`scripts/build_parser.py` 的編譯器解析順序為：`$CXX` 環境變數 → `g++` → `clang++`（找不到任一個則 `SystemExit`）；編譯 `src/eda_engine/parser/*.cpp` 中除 `parser.cpp`（明確排除）外的所有原始檔，使用 `-std=c++17`。

### 9.2 Dockerfile 規格

`Dockerfile` 為**兩階段建置**：

- **Stage 1（`abc-builder`，基底 `python:3.11-slim`）**：安裝 `g++ gcc make git`，`git clone --depth 1` Berkeley ABC 官方 repo 至 `/abc`，執行 `make -C /abc -j"$(nproc)" ABC_USE_NO_READLINE=1 abc` 建置出 ABC 執行檔。此階段的產物僅為 `/abc/abc` 這個二進位，其餘建置工具鏈不會進入最終映像。
- **Stage 2（最終映像，基底同為 `python:3.11-slim`）**：安裝 `g++`（供 `build_parser.py` 編譯 C++ parser 使用），`pip install -r requirements.txt`，`COPY . .` 複製整個專案原始碼，接著執行 `python scripts/build_parser.py` 編譯出 `parser_cpp`。**關鍵順序**：`COPY --from=abc-builder /abc/abc /app/tools/abc/abc` 刻意放在 `COPY . .` **之後**執行——確保 Stage 1 新建置的 ABC 二進位會覆蓋任何隨原始碼一併複製進映像的舊主機殘留檔案（`tools/abc/` 若在建置上下文中已存在過期二進位）。最終 `CMD ["./cada1066_alpha", "-config", "config.yaml"]` 以競賽入口點作為容器預設啟動命令。

`.dockerignore` 排除 `.git`、`venv`、`tools/abc`（避免主機端已建置的 ABC 誤入 build context）、`verification_runs`、`__pycache__`、`*.pyc`、`.env`、`A_20260212.pdf`、`testcase/*/*.log`、`testcase/*/*_out.v`。

**注意**：本開發機為共用機器且無 docker group 權限，實際 `docker build`/`docker run` 需請管理員協助執行，本節內容基於靜態檔案分析。

---

## 10. 程式碼品質標準

### 10.1 靜態分析規則（現況）

**目前無任何靜態分析工具配置**（無 `.ruff.toml`/`pyproject.toml` lint 設定、無 `.clang-tidy` 設定）。現有的事實查核點為：

- `py_compile`：可作為最低限度的 Python 語法正確性檢查。
- `netlist_oracle.py --selftest` 與 `check_answers.py --selftest`：邏輯自我檢查，不依賴真實 testcase 資料。
- CI 的單一整合測試（`tests/integration_tests/run_test.py`）。

**建議候選項**（尚未導入，列為未來改進方向）：Python 側導入 `ruff`（lint + format 合一，速度快）；C++ 側導入 `clang-tidy`（尤其可捕捉本文件第 6 節列出的 `stoi` 無防護、未使用型別 `SignalGroup` 等既知問題）。

### 10.2 Code Review 檢查要點

| 類別 | 檢查項目 |
|---|---|
| 正確性 | 是否保持功能等價性驗證（flop-cut BLIF + ABC `cec`）；轉換是否遵守協定不變量（`#RESPONSE`/`#END` 配對、`_loaded_filepath` 鏈接不可繞過、`verified_writes` 僅在磁碟驗證後才記錄） |
| 安全性 | （不適用一般 web 安全項目，改以本專案風險為準）subprocess 呼叫的引數是否經過妥善組裝（避免注入非預期旗標）、是否設定逾時（parser action 150 秒、ABC 呼叫 180 秒，皆須嚴格小於 270 秒的請求外層預算） |
| 效能 | 路徑枚舉等無界演算法是否有明確上限（對照 `r2r_paths` 的 `MAX_TOTAL_PATHS` 設計）；LLM context 是否落在 `_MAX_CONTEXT_CHARS` 預算內、大型工具結果是否觸發落地檔案機制 |
| 可維護性 | 命名是否清晰一致（C++/Python 側 action 名稱與 tool_spec 是否一一對應）、方法長度是否適當、`docs/OPEN_QUESTIONS.md` 中的規格模糊決策是否有對應註解可追溯 |
| 測試 | 新增轉換工具是否至少通過 `eval_harness.py` 的等價性與不變量檢查；新增分析工具是否在 `netlist_oracle.py` 有獨立實作可交叉核對（避免唯一真相來源） |

## 1. 文件資訊

| 項目       | 內容                    |
| -------- | --------------------- |
| **文件編號** | SDD-CADA1066-001      |
| **版本**   | v1.0                  |
| **建立日期** | 2026-07-06            |
| **最後更新** | 2026-07-06            |
| **撰寫者**  | cada1066 團隊            |

### 版本歷程

| 版本  | 日期         | 修改人     | 修改內容摘要 |
| --- | ---------- | ------- | ------ |
| v1.0 | 2026-07-06 | cada1066 團隊 | 初版     |

### 關聯文件

| 文件名稱                            | 文件編號                    | 版本  | 關聯性                       |
| ------------------------------- | ------------------------ | --- | ------------------------- |
| Technical_specification_document.md | TSD-CADA1066-CORE-001    | v1.0 | HOW 層：類別/函式/演算法/資料結構詳細規格，本文件不重複其內容，僅交叉引用 |
| OPEN_QUESTIONS.md                | -                        | -   | 規格模糊處之決策記錄，第 9 節設計決策記錄多數取材於此 |
| REPORT_transform.md              | -                        | -   | 轉換工具、測試案例與演算法對照報告          |
| EVAL_HARNESS.md                  | -                        | -   | 無金標評估工具鏈設計說明               |
| A_20260212.pdf                   | -                        | -   | ICCAD 2026 Problem A 競賽規格 |

---

## 2. 系統概述

### 2.1 競賽問題

ICCAD 2026 Problem A 要求參賽系統實作一個「自然語言驅動的網表分析/轉換」代理人：使用者以自然語言描述對一份閘級（gate-level）Verilog 網表的分析查詢或結構轉換需求，系統須理解意圖、呼叫適當工具完成任務，並在轉換類任務中保證輸出網表與原始網表功能等價。系統以 LLM（評測用小型模型）作為自然語言理解與工具呼叫決策的核心，實際的網表操作則交由確定性的 C++ 引擎與 Berkeley ABC 執行，LLM 本身不直接生成或判斷網表內容。

### 2.2 外部強制規格

以下規格由競賽評測程式（grader）強制要求，系統設計必須以此為不可協商的邊界條件：

- **輸入協定**：請求經 stdin 逐行送達，一行一個請求；系統以子行程常駐方式運作，每次啟動對應一個 testcase。
- **輸出協定**：每個請求的回覆必須包在 `#RESPONSE <id>` 與 `#END <id>` 之間並寫至 stdout；`<id>` 為每個 testcase 內單調遞增的回應序號。grader 以偵測到 `#END <id>` 作為送出下一行請求的訊號，故協定的即時性（flush）是硬性要求。
- **落地日誌**：每次回覆同步落地一份到 `<case_name>.log`，供事後稽核與除錯。
- **硬性需求違反 = 該案零分**：功能等價性、扇出上限、深度上限等硬性需求若有任一項不成立，該 testcase 不計部分分數，直接判零。
- **評測模型**：`claude-haiku-4-5` 與 `gpt-4o-mini` 兩種小型模型皆須被支援與評測。
- **時間預算**：規格明定基本操作 60 秒、其餘每請求 300 秒的時間上限；系統內部時間預算階層（見第 5.2 節）需嚴格低於此外部上限，保留邊際供協定收尾。

### 2.3 現況

以 `scripts/check_results.py --all` 為硬性需求檢查基準，目前於 `claude-haiku-4-5` 評測模型下達成 **40/40** 全數通過（見 `.claude/rules/agent-runtime.md`）。`gpt-4o-mini` 因 OpenAI API key 目前無 quota（429 錯誤）尚未能完整驗證（詳見第 10 節）。

---

## 3. 設計目標與約束

### 3.1 正確性優先：功能等價神聖

任何轉換操作，無論分析結果的措辭是否精準命中評測期待，最終輸出網表相對原始網表的**功能等價性**是最高優先級的設計目標。CLAUDE.md 明確規定：功能等價是神聖的（sacred），任何硬性需求違反導致該 testcase 零分、無部分分數。因此系統的每一個轉換工具（第 6.4 節、TSD 第 4 節）在設計上都以「先確保等價、再談是否精準符合措辭」為序，並提供獨立的 `check_equivalence` 工具（ABC `cec`）供 LLM 主動或系統被動驗證。

### 3.2 小型模型可靠性：核心設計問題

系統評測對象是 `claude-haiku-4-5` 與 `gpt-4o-mini` 這類小型模型，而非大型旗艦模型。這類模型有一個實測驗證過的系統性缺陷：**會在完全沒有呼叫任何工具的情況下捏造成功結果**——例如直接回覆「已成功寫入」、「已替換 138 個 XOR、新增 552 個 NAND」等具體數字，但實際上沒有執行任何操作、沒有任何檔案被寫入。`.claude/rules/agent-runtime.md` 記錄了此問題被發現前後的真實對照：**在防幻覺閘門與時間預算階層加入之前，23/40 個 testcase 遺失了輸出檔案，`check_results.py` 僅通過 16/40；加入三道防幻覺閘門與時間預算階層後，通過率提升到 40/40**。這組數字是本系統防幻覺設計（第 5.1 節）存在的直接理由，也是「小型模型可靠性」被列為與正確性同等重要之設計目標的實證依據。

### 3.3 確定性

除了 LLM 的自然語言理解與工具呼叫決策之外，系統的其餘部分——網表解析、圖論分析、結構轉換、等價性驗證——全部由確定性的 C++ 引擎與 ABC 完成，不依賴 LLM 生成任何網表內容或數值結果。這個劃分讓「LLM 可能出錯」的風險被侷限在決策層，而不會滲透到計算層；即使 LLM 選錯工具或給錯參數，計算結果本身仍是可重現、可驗證的。

### 3.4 每請求時間上限

每個請求必須在評測系統允許的時間內完成並送出 `#END`，逾時等同該請求失敗。系統內部設計了嚴格的時間預算階層（第 5.2 節），確保任何單一子行程（parser 動作或 ABC 呼叫）的逾時都不會讓整個請求無限期卡住，而是能在外層預算內回報一個可處理的錯誤訊息，讓 LLM 或系統本身有機會妥善收尾。

### 3.5 共享開發機約束

開發環境為共用機器，非獨立沙箱，這對日常開發流程施加了具體限制：

- **Python 執行環境**：僅使用系統 `python3`；專案內的 `./venv` 因缺少相依套件而損壞，不得使用。
- **無 docker group 權限**：無法直接執行 `docker build`/`docker run` 進行容器化驗證，需請管理員協助；Dockerfile 與 docker-compose 的正確性目前僅能透過靜態檔案審查確認（見第 10 節）。
- **OpenAI API 額度限制**：OpenAI key 目前無 quota，`gpt-4o-mini` 相關呼叫會收到 429 錯誤；日常開發與驗證以 Anthropic key/config 為主。
- **同機其他行程**：機器上可能同時有其他團隊成員的行程在跑，執行 sweep 等耗時操作前需留意資源競爭。

---

## 4. 系統架構

### 4.1 分層視圖

系統分為四層，層與層之間以行程邊界（subprocess boundary）明確切割，而非共享記憶體或常駐 IPC：

```
┌─────────────────────────────────────────────────────────────────┐
│ 協定層  src/utils/io_manager.py                                   │
│   stdin 逐行讀取、testcase-init 偵測、#RESPONSE/#END 協定輸出、雙 log 落地 │
└───────────────────────────────┬─────────────────────────────────┘
                                 │ 呼叫
┌───────────────────────────────▼─────────────────────────────────┐
│ 規劃層  src/agent/planner.py + llm_client.py                       │
│   LLM 工具呼叫迴圈（最多 10 輪）、三道防幻覺 gate、時間/context 預算控管      │
│   provider 路由（Anthropic / OpenAI）、重試退避                        │
└───────────────────────────────┬─────────────────────────────────┘
                                 │ dispatch（42 個工具 → engine 方法）
┌───────────────────────────────▼─────────────────────────────────┐
│ 執行層  src/eda_engine/engine.py                                  │
│   session 檔案鏈（_loaded_filepath）、磁碟驗證寫入、扇出約束重執行        │
│   每個 action 組裝 subprocess 呼叫（逾時控管）                          │
└──────────────┬──────────────────────────────────┬───────────────┘
       ══════════════ 行程邊界（每次呼叫全新子行程）══════════════
               │ subprocess                        │ subprocess
┌──────────────▼──────────────┐    ┌────────────────▼──────────────┐
│ 計算層 A：parser_cpp          │    │ 計算層 B：Berkeley ABC          │
│  （C++，Verilog 剖析/圖論分析/  │    │  （cec 形式等價驗證、             │
│   結構轉換/BLIF 匯出入）        │    │   resyn2/balance 深度最佳化）     │
└──────────────────────────────┘    └───────────────────────────────┘
```

協定層與規劃層存活於同一個 Python 常駐行程內（`main.py` 主迴圈期間持續存活），執行層（`EDAEngine`）也在同一行程中，但它每次呼叫 parser 或 ABC 時都會 fork 出一個全新的子行程，該子行程執行單一 action 後即結束。這代表**計算層完全無狀態**——`parser_cpp` 每次呼叫都是「讀檔案 → 建圖 → 執行一個 action → 印結果 → 結束」，圖結構不會跨行程存活；狀態的連續性完全由 Python 層以 session 檔案鏈（第 4.3 節、7.2 節）維持。

### 4.2 請求生命週期

單一 stdin 請求從輸入到輸出的完整路徑：

```
stdin 讀入一行
  │
  ├─ 空行 → 靜默跳過
  ├─ testcase-init 訊息 → io_mgr.init_testcase() + planner.reset()，直接回覆（不經 LLM）
  └─ 一般 EDA 請求 → planner.process(line)
        ├─ 組裝 messages（system prompt + 歷史 + 本次請求）
        ├─ LLM 工具呼叫迴圈（至多 10 輪）：
        │    LLM.chat() → 若有 tool_calls → 逐一 dispatch 到 EDAEngine 方法
        │                    → EDAEngine 組裝並執行 subprocess（parser_cpp 或 ABC）
        │    → 若 LLM 回傳純文字 → 通過三道防幻覺 gate 判定是否接受此答案
        └─ 回傳最終 answer 字串
  │
  └─ io_mgr.write_response(answer)
        ├─ response_id 遞增
        ├─ 組出 "#RESPONSE {id}\n{text}\n#END {id}\n"
        ├─ 寫 stdout 並立即 flush（唯一允許寫 stdout 之處）
        └─ 同步寫入 log 檔（雙 sink）並 flush
```

### 4.3 架構決策依據

**每動作一個子行程（故障隔離）**：`EDAEngine` 對每一個工具呼叫都組裝一次 `subprocess.run([parser_cpp, --in, ..., --action, ...], timeout=150)`（或對 ABC 呼叫 `timeout=180`），而非把 `parser_cpp` 作為常駐服務保持一個長壽命行程。這個決策的理由是**故障隔離**：C++ 引擎若因某個邊界情況崩潰（例如未防護的 `std::stoi` 例外導致 `terminate`）或陷入無界計算（例如 `find_all_paths` 在高扇出網格上的指數爆炸），影響範圍被限制在「這一次工具呼叫」，而不會拖垮整個常駐 Python 行程或汙染後續請求的狀態。同時，OS 層級的 subprocess timeout 提供了一個 C++ 程式碼內部無法自行保證的強制終止機制——即使 C++ 引擎某個演算法沒有內建的深度或路徑數上限（詳見第 10 節「已知限制」第 1 項），外層的 150 秒行程逾時仍能確保該次呼叫不會無限期佔用請求預算。

**Session 檔案鏈（中間狀態不可變、原始檔保留）**：`EDAEngine` 以 `_loaded_filepath`（目前作用中的設計檔案）與 `_original_filepath`（原始檔案，永久保留）兩個指標管理狀態。每個 transform 方法產生一個新的 session 檔案並重新指向 `_loaded_filepath`，形成「原始檔 → session 檔案 1 → session 檔案 2 → ...」的鏈，而不是就地修改（in-place mutate）同一個檔案。這個設計有兩個理由：其一，中間狀態的不可變性讓除錯與追溯變得容易——任何一步的輸入輸出都是獨立檔案，可回頭檢查；其二，`_original_filepath` 的永久保留是**形式等價驗證的必要前提**：`check_equivalence` 預設比對「目前 `_loaded_filepath`」對「`_original_filepath`」，若沒有保留原始檔，就無法對任意一步之後的網表做等價性證明。

**評估器與受測工具互相獨立（不自證）**：四層評估體系（第 8 節）中，`check_results.py` 使用**自帶的 mini-parser**重新解析輸出網表，而非重用 `parser_cpp`；`netlist_oracle.py` 也自帶獨立的 BLIF writer，而非借用 `parser_cpp` 的 `write_blif`。這個決策的核心理由是避免「被測系統驗證自己」的邏輯迴圈——如果驗證邏輯與被驗證的實作共用同一份程式碼，兩者共同的 bug 會被系統性地漏掉。等價性驗證本身則是例外：`check_results.py` 的等價性檢查仍然透過 `parser_cpp` 的 `write_blif` 交給 ABC `cec`，因為等價性判定的數學核心（SAT-based 形式驗證）由 ABC 這個外部黑盒工具負責，其正確性不依賴 `parser_cpp` 的其餘邏輯是否正確。

---

## 5. 可靠性設計

### 5.1 防幻覺三閘門

三道 gate 全部實作於 `Planner.process`（`planner.py:269-304`），共用同一個 `corrections` 計數器（上限 2 次，見下）。每一道 gate 都對應一種在加入防護之前實測觀察到的具體捏造模式：

1. **Zero-tool gate**：若 LLM 在本輪完全沒有呼叫任何工具就直接給出答案——例如聲稱「已完成分析」但沒有呼叫任何分析工具——該答案被拒絕並要求 LLM 先呼叫工具再回答。這是最基礎的一道防線：沒有工具呼叫，就沒有任何實際發生的計算或測量，任何具體數字或結論都只能是捏造。
2. **Write gate**：若請求文字命中寫入意圖正則 `_RE_WRITE_INTENT`（匹配 `write|save|output|export|dump` 等關鍵詞加 `.v` 副檔名），則只有當 `engine.verified_writes`（第 5.4 節）中出現本輪新增且檔名相符的紀錄時，答案才被接受。這道 gate 對應的具體捏造案例是：LLM 直接回覆「已成功寫入 `test_out.v`」，但實際上從未呼叫 `write_design`，磁碟上根本不存在該檔案——這正是加入防護前 23/40 個 testcase 遺失輸出檔案的直接成因。
3. **Transform gate**：若請求非問句（不以 `?` 結尾）且命中轉換意圖正則 `_RE_TRANSFORM_INTENT`，但本輪執行過的工具集合與 17 種 transform 工具集合（`_TRANSFORM_TOOLS`）沒有交集，答案被拒絕。這道 gate 對應的捏造案例是 CLAUDE.md 與 agent-runtime.md 中提到的「138 XOR replaced, 552 NAND added」這類極具體卻完全未經計算的數字——LLM 在沒有呼叫任何 `decompose_*`/`convert_cone_to_basis`/`reconstruct_netlist_to_basis` 等工具的情況下，直接生成看似合理的轉換統計數字。

**Correction cap**：三道 gate 共用 `corrections < 2` 的上限。一旦某一輪因不滿足任一 gate 被要求修正，`corrections` 遞增；超過上限後，若原始請求屬於 write 意圖，系統直接回覆明確的失敗訊息（"the output file could not be written despite repeated attempts"）而不再迴圈；非 write 請求則直接跳出迴圈，保留當輪未通過 gate 的文字作為最終答案。這個上限的存在理由是避免「LLM 持續給出無工具支持的答案 → gate 拒絕 → LLM 再次給出類似答案」的無限迴圈耗盡請求的時間預算——與其讓迴圈耗到逾時，不如在有限次數的修正嘗試後承認失敗並誠實回報。

三道 gate 加上時間預算階層（5.2 節）共同構成的實測效果：**加入前 16/40 通過、加入後 40/40 通過**（`.claude/rules/agent-runtime.md`），這組對照數字是本節設計存在的第一手證據，而非理論推導。

### 5.2 時間預算階層表

| 層級 | 值 | 常數/位置 | 理由 |
|---|---|---|---|
| 請求牆鐘預算 | 270 秒 | `Planner._REQUEST_BUDGET_S`（planner.py:31） | 規格限制每請求 300 秒；保留 30 秒邊際確保仍能送出 `#END` |
| ABC 呼叫（cec / reduce_depth） | 180 秒 | `engine.py` 兩處 `subprocess.run([abc_path, ...], timeout=180)`（engine.py:457, 778） | 大型設計上 ABC 重構/等價性檢查可能耗時較久，但仍須低於 270 秒外層預算 |
| 功能恆定分析預算（P1-8） | check_const 110 秒 / functional report-tie 批次 80 秒 / 單次 ABC SAT 20 秒 | `EDAEngine._CONST_BUDGET_S` / `_FUNC_BUDGET_S` / `_SAT_TIMEOUT_S` | 模擬+SAT 證明流程的牆鐘上限;SAT 逾時會被夾到剩餘預算,逾時不視為證明(僅 UNSAT 算恆定),整體低於 270 秒請求預算 |
| Parser 動作子行程 | 150 秒 | `EDAEngine._ACTION_TIMEOUT_S`（engine.py:26） | 限制如指數級路徑枚舉等無界計算（test12 需要此上限；`eval_harness.py` 內建的獨立 oracle 對同一查詢秒答，凸顯工具本身的逾時是設計問題而非查詢過難） |
| LLM 迭代上限 | 10 輪 | `Planner._MAX_ITERATIONS`（planner.py:30） | 每請求最多 10 輪 LLM↔工具往返，避免無限迴圈；與時間預算是獨立的兩種終止條件 |
| LLM 重試退避 | (2, 8, 20) 秒，共 4 次嘗試 | `LLMClient._RETRY_DELAYS_S`（llm_client.py:93） | 對暫時性供應商錯誤（rate limit/overload）指數式退避重試 |

**外層必須大於內層的不變量**：這個階層表不是四個互不相干的數字，而是一條必須維持的不等式鏈：`_ACTION_TIMEOUT_S`(150) < ABC timeout(180) < `_REQUEST_BUDGET_S`(270) < 評測規格上限(300)。`.claude/rules/agent-runtime.md` 明確指出，若這個不等式被打破——例如某個內層逾時被誤改為大於等於外層預算——一次緩慢的內層呼叫會**靜默地**吃光外層預算，導致該請求根本沒有機會在 grader 自己的逾時之前送出 `#END`。這類迴歸不會在 `run_all_llm.py` 的「OK」狀態中顯現（因為協定本身可能仍然完成，只是耗時異常），必須靠 `check_results.py` 或對逐案耗時的觀察才能發現，故任何調整這組常數的改動都必須重新驗證整個不等式鏈，而非只驗證單一數字本身是否合理。

### 5.3 Context 收縮

`Planner` 對 LLM 對話 context 的字元預算控管採**主動 + 反應式**雙軌設計：

- **主動收縮**：每輪呼叫 LLM 前，檢查訊息總字元數是否超過 `_MAX_CONTEXT_CHARS = 300_000`（planner.py:322），超過則保留最近 `_KEEP_RECENT_TOOL_RESULTS = 2` 筆完整工具結果，其餘壓縮/摘要。
- **反應式收縮**：當 `LLMClient.chat()` 拋出的例外文字包含 "prompt is too long" 字樣時（代表主動收縮的估算仍然偏樂觀、實際觸底了供應商的硬性上限），以更激進的參數（`keep_recent=1, limit=0`）強制收縮後 `continue` 重試同一輪，而非直接放棄整個請求。

**閾值刻意保守的教訓**：`_MAX_CONTEXT_CHARS` 訂為 300k 字元，遠低於一般 200k-token API 上限對應的字元數估算。理由記錄於程式註解與 TSD：netlist 中的識別符（如冗長的自動產生閘名、訊號名）字元密度顯著高於一般自然語言文字——約 **2 字元/token**，而非一般文字常見的 4 字元/token 估算。若沿用一般文字的估算比例，同樣字元數的網表相關 context 會消耗遠超預期的 token 數，導致主動收縮的觸發時機太晚。test33、test40 是促成這個保守化決策的具體案例——這兩案在早期版本中曾因保留過多工具結果、以偏樂觀的字元/token 比例估算，觸發了未被主動收縮攔截的 "prompt too long" 錯誤，才促使閾值與保留策略被下修。

### 5.4 磁碟驗證寫入與扇出約束重執行

**磁碟驗證寫入（`verified_writes`）**：`EDAEngine.write_design`（engine.py:321-344）在呼叫 parser 的 `write` action 並收到內含 "Success" 的回傳字串後，**不直接信任**這個自報成功——而是額外呼叫 `os.path.isfile(filepath)` 二次驗證檔案確實存在於磁碟上，只有通過此驗證才將絕對路徑加入 `self.verified_writes`。這個設計直接呼應 parser_cpp 的一個已知風險：`write`/`write_blif` action 在缺少 `--out` 旗標時會**靜默失敗**——`log_error` 之後沒有 `return 1`，exit code 仍是 0，也沒有印出任何 "Success" 字樣，但如果只看 exit code 會被誤判為成功。`verified_writes` 這個磁碟層級的二次驗證正是為了不讓這類靜默失敗滲透到上層——它同時也是 write gate（5.1 節）判斷「這次請求是否真的完成了寫入」的唯一資料來源。

**扇出約束重執行（OPEN_QUESTIONS D3）**：一旦任何請求呼叫過 `insert_buffers(max_fanout)`，引擎會記住 `self._max_fanout_constraint = max_fanout`。這個約束之後在兩個地方被**主動重新套用**：`reduce_depth`（因為 ABC 的 `strash`/`resyn2` 重構會把先前插入的緩衝閘連同其餘組合邏輯一起打散重建，扇出限制因此可能失效）與 `write_design`（作為最終輸出前的保證）。`docs/OPEN_QUESTIONS.md` D3 將此列為「工程預設」（⚠️ 而非 ✅ 已與使用者確認的決策）：由於後續轉換（深度最佳化、cone 轉換、反閘收合）都可能在不知情的情況下把扇出重新推高過門檻，若不主動重執行，先前請求建立的扇出保證會被靜默破壞而不自知。設計上選擇讓引擎「記得」曾經被要求過的約束並在關鍵時點自動重新套用，而非要求 LLM 每次轉換後自行重新檢查並重新呼叫 `insert_buffers`——因為後者依賴 LLM 主動記得這件事，與第 3.2 節「小型模型可靠性」的核心顧慮直接衝突。

---

## 6. 介面設計

### 6.1 對外協定

stdin/stdout 協定由 `IOManager`（`src/utils/io_manager.py`）獨佔實作，其不變量：

- **唯一 stdout 寫入點**：整個系統中，只有 `IOManager.write_response` 被允許寫 stdout；所有記錄用途的輸出（`logging.basicConfig`）一律導向 stderr。這個劃分確保 grader 解析 stdout 時不會被任何除錯訊息汙染協定格式。
- **`#END` 後立即 flush**：grader 的行為是偵測到 `#END <id>` 才送出下一行請求，因此 `write_response` 在寫完 `#RESPONSE {id}\n{text}\n#END {id}\n` 後必須立即呼叫 `sys.stdout.flush()`——若省略這一步，內容可能停留在緩衝區而讓 grader 誤判為逾時。
- **response id 單調且每案重置**：`response_id` 在單一 testcase 生命週期內單調遞增，並在每次偵測到 testcase-init 訊息時重置為 0（透過 `init_testcase`）。
- **雙 log 落地**：每次回覆同步寫入 `<case_name>.log`（CWD 下必有）與（若目錄存在）`testcase/<case_name>/<case_name>.log` 兩份，兩者與 stdout 內容逐字元相同——這個逐字元相等性由 `tests/integration_tests/run_test.py` 明確斷言。

### 6.2 LLM 工具介面

`tool_spec.py` 定義 42 個結構化工具供 LLM 呼叫，分為四大類：**IO 類**（`load_design`/`write_design`，2 個）、**ANALYSIS 類**（唯讀查詢，不改變 `_loaded_filepath`，22 個）、**TRANSFORM 類**（改變 `_loaded_filepath` 指向，17 個，與 `Planner._TRANSFORM_TOOLS` 集合一致）、**VERIFY 類**（`check_equivalence`，1 個）。完整的工具清單、各工具參數簽名與對應 engine 方法，見 TSD 第 3.4 節工具面規格；本文件不重複列出，僅強調介面設計上的兩個跨工具共用機制：

- 42 個工具定義與 `Planner._dispatch` 字典**完全一一對應**（無缺漏、無多餘），dispatch 表建構於 `Planner.__init__`。
- **大結果落地截斷機制**：任何工具的原始輸出經 `Planner._execute_tool` 後，都會通過 `_truncate_large_result` 過濾——超過 `_MAX_RESULT_CHARS = 12000` 字元（約 3000 token，對任何供應商皆安全）的結果，不會整份塞回 LLM 的 context，而是落地為 `<tool_name>_<arg_tag>.log` 檔案（存於已載入設計同目錄），並回傳含 `notice`/`saved_to_file`/樣本欄位的 JSON 摘要。system prompt 明確要求 LLM 必須在回覆中提及 `saved_to_file` 路徑，讓使用者知道完整結果的落地位置。`find_paths` 另有專用的**完整枚舉落檔**路徑（C++ `--paths_out` 流式寫檔，2026-07-11，A16 合規——通用攔截層落的是「截斷後原文」，此處落的是完整清單），細節見第 10 節與 TSD §4.2(2)/§6.1。

### 6.3 parser_cpp CLI 契約

`parser_cpp` 以 `--in <file.v> --action <action> [--key value ...]` 的簡單旗標配對呼叫慣例運作。介面設計上有兩個對上層（Python 執行層）至關重要的契約特性：

- **stdout 首行字串為事實 API**：`parser_cpp` 對每個 action 的**輸出首行字串格式**（例如 `load` 的 `"Success. PI: N, PO: N, Gates: N"`、`replace_gate` 的 `"Success"`/`"Failure"`）才是 Python 層實際依賴的介面，而非任何結構化的回傳碼或機器可讀格式（JSON 輸出的少數 action 例外，見 TSD 第 2 節 CLI 表）。這個「輸出字串即 API」的設計沒有 schema 版本控管，任何未來對輸出字串格式的調整都是破壞性變更。
- **exit code 不可靠，需以字串判斷成敗**：絕大多數 `Graph::` 方法回傳的字串本身內嵌 `"Error: ... not found."` 或 `"Failure: ..."` 前綴，但這些**不是例外、也不設定非零 exit code**——`main.cpp` 對這些呼叫一律 `return 0`。因此上層無法依賴 process exit code 區分「找不到節點」與「成功」，必須解析 stdout 字串內容。歷史教訓：`write`/`write_blif` action 缺少 `--out` 旗標時曾**靜默失敗**（exit code 0、無任何 stdout 輸出）——此問題已於 2026-07-06 修復（補上 `return 1`），但它是第 5.4 節 `verified_writes` 磁碟二次驗證機制誕生的直接理由；該機制保留作為縱深防禦：介面契約以字串為準的本質未變，上層仍以獨立手段（`os.path.isfile`）驗證副作用是否真的發生。

2026-07-11（P1-8）新增五個 action，沿用同一 CLI 契約:`report_stuck_inputs`（`--gate_type --cycles --trials --seed`,列出模擬中從未離開單一值的候選閘輸入,`CAND gate=... input=... stuck=... structural=...` 逐行）、`sim_consts`（`--nets` CSV,回報各網 0/1 觀察次數）、`write_cone_blifs`（`--nets --out_dir [--tie0]`,批次匯出各網組合 cone 的 BLIF 供 ABC SAT）、`list_dffs`（`--scope_net?`,列 DFF 的 Q/D 網名）、`tie_nets_const`（`--assign net=0/1,... --out`,把證明恆定的網綁上常數後回寫）。隨機模擬核心 `run_random_sim` 以一次性稠密節點編號＋扁平閘程式執行(2026-07-11 效能修復:100k 節點 16×64 拍 ~90s → ~5s,舊版逐拍 unordered_map 曾使 test39 整案逾時)。

### 6.4 ABC 介面

系統以兩種用途呼叫 Berkeley ABC，兩者共用同一個橋接格式：**flop-cut BLIF**（正反器切割 BLIF）。橋接規則（`Graph::write_blif`，詳見 TSD 4.2 節(1)）：每個 DFF 的 **Q 輸出網路映射為 BLIF 的 `.inputs`**（代表「上一狀態」），每個 DFF 的 **D 輸入映射為新的 `.outputs` 項 `__D_<inst>`**（代表「下一狀態」）；若某 PO net 恰好也是某 DFF 的 Q net，該 PO 從 `.outputs` 省略（因等價性已由對應 `__D_<inst>` 涵蓋）。這個橋接把時序電路轉換成 ABC 能處理的純組合邏輯，兩種用途分別是：

1. **`cec`（形式等價驗證）**：`check_equivalence` 對「目前 `_loaded_filepath`」與「參照網表（預設 `_original_filepath`）」各自匯出 flop-cut BLIF，交給 ABC `cec` 做 SAT-based 組合等價驗證。
2. **`resyn2`（深度最佳化）**：`reduce_depth` 匯出目前設計的 flop-cut BLIF，跑 `strash; balance; resyn2; balance` 序列，再透過 `load_logic_blif` + `rebuild` action 把最佳化後的 AIG 讀回並重新接上原有的正反器與控制腳。

flop-cut 模型的健全性有明確邊界：它僅對「保留正反器邊界」的轉換（緩衝、深度最佳化、掃除、重新命名、分解、基底重映射、反閘收合）成立；任何新增/刪除/合併正反器的轉換會讓 flop-cut `cec` 誤判為不等價（`docs/OPEN_QUESTIONS.md` D6，詳見第 9 節決策記錄）。

---

## 7. 資料設計

### 7.1 網表圖表示

C++ 引擎以**指標鄰接表**（非集中式邊表、非鄰接矩陣）表示網表圖：每個 `Node` 自帶 `std::vector<Node*> inputs`/`outputs`，有向邊以雙向記錄（`from->outputs` 推入 `to`，同時 `to->inputs` 推入 `from`）。所有權模型上，`Graph::all_nodes`（`std::vector<Node*>`）是唯一的擁有權容器，`Graph::nodes`（`std::unordered_map<std::string, Node*>`）僅是名稱→節點的查找別名索引，不擁有記憶體；其餘所有中間容器（拓撲序快取、演算法內的暫存 visited-set 等）都是非擁有性的裸指標容器。

**DFF 控制腳與圖邊分離儲存**是這個資料設計中最關鍵的一個決策：只有具名接腳（named-port，如 `.CK(clk)`）的閘（主要是 DFF）才會填入 `pin_conns` 欄位；控制腳（CK/RN/SN）僅記錄在 `pin_conns` 裡（`edge_dir==0`，無圖邊對應），不建立 `inputs`/`outputs` 圖邊，而資料腳（D/Q）才同時建立圖邊並記錄 `edge_dir`（1=輸入邊、2=輸出邊）。這個分離讓「時序控制邊界」與「一般組合邏輯資料流」在資料結構層級就明確區隔，也是拓撲排序、層級化計算等演算法能夠正確地把 DFF 視為時序邊界（而非把控制訊號誤當成資料流）的基礎。

### 7.2 檔案佈局

```
testcase/<case_name>/
  ├── prompt.txt         # 逐行請求腳本
  ├── <case_name>.v      # 輸入 Verilog 網表
  ├── <case_name>_out.v  # 轉換後輸出網表（write_design 產生）
  └── <case_name>.log    # 協定回覆的雙 sink 落地之一

<CWD>/<case_name>.log     # 協定回覆的雙 sink 落地之二（必有）

<tempfile.mkdtemp() session_dir>/
  ├── <tag>_1.v          # 第一個 transform 產生的 session 檔案
  ├── <tag>_2.v          # 鏈接自前一份
  └── ...                # 每個 transform 依序產生，_loaded_filepath 依序指向最新一份

/tmp/grader_sim/          # grader_sim.py 除錯用單案模擬輸出落點
```

session 檔案鏈的細節見第 4.3 節；`_original_filepath` 不在此鏈中變動，永久指向 `testcase/<case_name>/<case_name>.v`，供等價性驗證使用。

### 7.3 BLIF 中介格式

BLIF（Berkeley Logic Interchange Format）是 Python/C++ 層與 ABC 之間的中介資料格式，僅在 `write_blif`/`load_logic_blif`/`rebuild` 三個 action 中出現，不對 LLM 或使用者直接曝露。其角色定位：BLIF 本身不是系統的「原生」網表表示（原生表示是 Verilog + 記憶體中的 `Graph` 物件），而是**專為與 ABC 交換資料而存在的臨時格式**，且僅承載組合邏輯（flop-cut 之後）——正反器本身及其控制腳連線不進入 BLIF，而是在 `rebuild` action 中由 Python 層另行以原始 `pin_conns` 資料重新接上（見第 6.4 節）。BLIF 匯入端目前僅支援 `nin<=2` 的真值表區塊（詳見第 10 節已知限制第 1 項），這是 BLIF 中介格式在本系統中的一個明確能力邊界。

---

## 8. 品質保證體系

系統以四層獨立評估工具鏈驗證正確性，各層針對不同的失敗模式，缺一不可：

| 層級 | 腳本 | 它防住什麼 |
|---|---|---|
| 1. 協定完成度 | `scripts/run_all_llm.py` | 防止「協定卡住/逾時/API 中斷」被誤判為靜默通過——只保證所有輪次都送出了 `#END` 且輸出檔存在，明確不等於分數，也不檢查內容正確性 |
| 2. 硬性需求 | `scripts/check_results.py` | 防止「協定完成但內容違反硬性需求」被漏檢——以獨立 mini-parser 重新解析輸出網表，檢查等價性、扇出上限、基底純度等，任何硬性項目失敗直接判該案零分 |
| 3. 無金標目標指標 | `scripts/eval_harness.py` | 防止「沒有標準答案可比對」導致無從發現結構性 bug——用等價性證明、不變量檢查、獨立 oracle 差分測試，在完全不依賴人工答案的情況下抓出真實邏輯錯誤 |
| 4. 分析答案正確性 | `scripts/check_answers.py` + `netlist_oracle.py` | 防止「轉換都對但分析類回答的具體數字/結論是錯的或是捏造的」被前三層漏掉——對分析類問句的回覆文字做正則抽取後與獨立 oracle 交叉核對 |

**獨立性原則**：如第 4.3 節所述，`check_results.py` 自帶 mini-parser、`netlist_oracle.py` 自帶 BLIF writer，兩者都刻意不重用 `parser_cpp` 對應的實作，理由是避免評估邏輯與被評估邏輯共用同一份程式碼、共同的 bug 因此被系統性地漏掉。等價性驗證是唯一的例外——其數學核心委託給外部黑盒工具 ABC，不受此獨立性原則侷限。

**Selftest 進入點**：`netlist_oracle.py --selftest` 對內建微型網表跑手算斷言，並對 test01/04/05/21 與 `parser_cpp` 交叉比對；`check_answers.py --selftest` 用合成 fixture 驗證評分邏輯本身正確，皆不依賴任何真實 testcase 資料，可在不消耗 API 額度的情況下快速驗證評估工具鏈本身沒有壞掉。

**CI 現況（誠實記載）**：CI（`.github/workflows/ci.yml`）目前只執行**單一 deterministic 整合測試**——以 `DeterministicLLMClient`（規則式 stub）取代真實 LLM API，跑一次 `main.py` 主迴圈邏輯，斷言 response id 序列、`#END`/`#RESPONSE` 對應、log 與 stdout 逐字元相等。CI **不**建置 ABC、**不**執行 `check_results.py`/`eval_harness.py`/`check_answers.py`、**不**呼叫真實 LLM API。真正的功能與品質保證主要落在上述系統級四層評估工具鏈上，而非 CI 本身——這是現況的如實記載，而非目標狀態；CI 覆蓋薄弱本身也列於第 10 節已知限制中。

---

## 9. 設計決策記錄

| 決策 | 日期 | 理由 | 後果 |
|---|---|---|---|
| 改良既有系統而非重寫 | 2026-07-03 | 既有系統已具備可運作的核心（parser、engine、40/40 硬性需求通過率），重寫的風險（時間成本、重新引入已修過的 bug）高於漸進改良 | 開發策略以最小變更達成改善為原則，變更前後皆須以 `--case <n>` 驗證，避免對已驗證行為的迴歸 |
| flop-cut 組合等價驗證 | - | 需要一個能與 ABC 交換的組合邏輯表示；DFF Q→輸入、D→輸出的切割規則讓時序電路能被當作純組合 DAG 驗證 | 對保持正反器邊界的轉換（緩衝、深度最佳化、掃除、重新命名、分解、基底重映射、反閘收合）是健全的；任何新增/刪除/合併正反器的轉換會讓 flop-cut `cec` 誤判為不等價（`docs/OPEN_QUESTIONS.md` D6），需改用真正的循序等價驗證（ABC `dsec`），目前尚未建置 |
| BUF 豁免基底純度 | - | 扇出限制、禁止反閘背對背收合、與嚴格基底純度三者無法同時滿足（`docs/OPEN_QUESTIONS.md` D2）；BUF 依標準 EDA 慣例本非邏輯閘 | 扇出限制優先於基底純度；最終網表在目標基底邏輯之外允許 BUF 存在以滿足扇出上限，一個嚴格逐閘型別檢查基底純度的評分方式會誤判 BUF 為違規 |
| 扇出約束持續化 | - | `reduce_depth`（ABC strash）與部分 cone 轉換會打散先前插入的緩衝閘，導致扇出限制悄悄失效（`docs/OPEN_QUESTIONS.md` D3） | 引擎記住曾被要求的 `max_fanout` 並在 `reduce_depth`、`write_design` 中自動重新套用；風險低，但依賴引擎主動記憶而非 LLM 主動重新檢查 |
| cone 穿越 DFF | - | 若嚴格以組合邏輯定義 cone，暫存器輸出的扇入 cone 為空，「轉換 cone 中所有閘」等請求會無事可做（`docs/OPEN_QUESTIONS.md` D4） | cone 遍歷穿越正反器（沿 D 輸入繼續往回走，以 visited-set 防護回饋環），得到實際計算該輸出的邏輯；風險是遍歷範圍可能跨越暫存器級數，比評分者預期的「僅前一級 D 邏輯」更大，但功能上安全 |
| 防幻覺閘門 | 2026-07-03 | 小型評測模型會在未呼叫工具的情況下捏造成功結果與具體數字（第 3.2、5.1 節） | 加入前 `check_results.py` 通過率 16/40，加入三道 gate + 時間預算階層後 40/40；correction cap 為 2 次，超過後誠實回報失敗而非無限重試 |
| per-action timeout 150 秒 | - | test12 的路徑枚舉在特定網表結構下呈指數級展開（`find_all_paths` 無界，見第 10 節） | 150 秒作為子行程強制終止的 OS 層保障，必須嚴格小於外層 270 秒請求預算；`eval_harness.py` 內建 oracle 對同一查詢秒答，證明逾時是引擎演算法設計問題而非查詢本身困難 |
| context 收縮 | - | test33、test40 曾因網表識別符字元密度（約 2 字元/token）高於一般文字，以樂觀比例估算導致觸發未被攔截的 "prompt too long" 錯誤 | 主動收縮閾值刻意保守（300k 字元）；反應式收縮作為第二道防線，在例外實際發生時以更激進參數強制收縮重試 |
| rename 優雅失敗 | - | 部分請求要求重新命名的閘會在後續 `reduce_depth` 中被 ABC 重構整個吸收消失，且無論如何重排轉換順序都無法保留該閘的具體命名（`docs/OPEN_QUESTIONS.md` D1） | `rename_node` 誠實回報「not found」而非偽裝成功；功能等價性（主要評分項）不受影響，僅重新命名這個子項可能因評分方式而失分 |

---

## 10. 已知限制與技術債

### C++ 引擎層（2026-07-06 修復批次後的狀態）

以下六項為程式碼審查（2026-07-06）發現的缺陷，同日完成修復；保留於此作為設計記錄：

- **BLIF 匯入 `nin>=3` 缺口**（已修復為大聲失敗）：原本超過兩輸入的 `.names` 區塊會落入 2-input 分支建出**錯誤邏輯**；現在 `flush` 在真值表展開前攔截並累計 `blif_unsupported`，`rebuild` 偵測到即回報 `Failure` 並以非零 exit code 中止。完整支援 3+ 輸入查表仍未實作——目前 ABC 腳本（`strash`/`resyn2`/`balance`）僅產生 2-input AIG，無實際需求;若未來變更 ABC 腳本，失敗會是顯性的而非靜默的。
- **`find_all_paths` 無界枚舉**（已修復；2026-07-11 擴充流式落檔）：加入目標可達性剪枝（反向 BFS 標記可達終點的子圖）與 10000 條收集上限；達上限時輸出附註 `count_paths` DP 的精確總數。實測：test12 原本 150 秒逾時的查詢，剪枝後 8 秒內完成（實際僅 8 條路徑——原本的耗時全部來自死路子圖的指數遊走）。150 秒 per-action timeout 保留作為一般性保險。**2026-07-11（官方 Q&A A16/A21.3，P1-3）**：新增 `--paths_out <file>` 流式模式——逐條寫檔不進記憶體，檔案為完整枚舉（test14 的 289,366 條實測全數落檔，行數與 DP 精確值相符，1.9 秒）；此模式防護為資源上限 10^6 條/512MB（無上限時病態配對可在 150 秒逾時前寫出數十 GB），觸頂時 header 明示 INCOMPLETE 並附 DP 精確總數。`count_paths` 同時改為 64 位元飽和加法（`int` 對指數成長的路徑數在隱藏測資上可能溢位）。Python 端 `engine.find_paths` 一律走流式模式，>50 條時把完整檔移入測資目錄並回 `saved_to_file` 摘要。
- **`stoi` 缺乏例外防護**（已修復於 CLI 層）：`main.cpp` 數值旗標改經 `int_flag()` 解析，非數字值 `log_error` 後乾淨退出。
- **拓撲快取失效不一致**（已修復）：`add_edge` 與三個節點刪除函式（`sweep_dangling`、`collapse_inverters`、`merge_duplicate_gates`）現在都顯式清空 `topological_order`，覆蓋所有變更圖結構的路徑。
- **`anon_N` 命名碰撞**（已修復）：匿名實例命名現在會跳過輸入網表已使用的名稱，不再靜默誤合併。
- **`SignalGroup` 死程式碼**（已移除）。

### 系統層

- **分析答案覆蓋缺口**：`check_answers.py` 對分析類回答的正確性裁決中，統計上有 **47/277** 筆判定為 `UNVERIFIED`（既非 CORRECT 也非 WRONG，而是無法以既有 oracle 邏輯核實），代表獨立 oracle（`netlist_oracle.py`）尚未覆蓋所有分析問句類型，這部分答案的實際正確性目前無從獨立驗證。
- **`gpt-4o-mini` 未驗證**：OpenAI API key 目前無 quota，任何 `gpt-4o-mini` 相關呼叫會以 429 失敗；40/40 的通過率僅在 `claude-haiku-4-5` 下實測驗證，`gpt-4o-mini` 路徑（provider 路由、訊息格式轉換等）僅經程式碼審查、未經真實流量驗證。
- **Docker 未實測**：開發環境無 docker group 權限，無法直接執行 `docker build`/`docker run`；Dockerfile 多階段建置、`.dockerignore` 排除規則的正確性目前僅基於靜態檔案審查，未經實際容器建置與執行驗證。
- **test37 cone 需求互斥**：test37 中 `n8`（NAND+NOT）與 `n9`（NOR+NOT）兩個 cone 需求在共享閘上重疊，無法同時嚴格成立；`check_results.py` 的處理方式是把 `n8` 標記為 `warn`（軟性）、`n9` 作為硬性檢查項，這是一個已知且記錄在案的規格層級衝突，而非程式錯誤。
- **CI 覆蓋薄弱**：如第 8 節所述，CI 僅執行一條以 deterministic stub 取代真實 LLM 的整合測試路徑，不涵蓋硬性需求、無金標指標、分析答案正確性三層評估，也不建置 ABC；真正的品質保證高度依賴人工於本機執行系統級評估工具鏈，而非自動化 CI 把關。

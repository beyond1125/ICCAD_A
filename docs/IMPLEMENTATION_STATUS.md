# 實作狀態追蹤（Implementation Status）

本文件追蹤 **SDD 已規劃、但程式尚未完成** 的項目。  
SDD 描述「系統應有的能力」；本文件描述「目前做到哪裡」。

> 更新時機：每次 merge 功能分支、或 SDD 模組/Tool 清單變更時同步修訂。

## 狀態定義

| 狀態 | 說明 |
|------|------|
| ✅ 已完成 | 行為與 SDD 一致，且有測試或手動驗證紀錄 |
| 🟡 部分完成 | 有初版實作，但行為、邊界或測試尚未達 SDD |
| ⬜ 未開始 | SDD 已描述，程式碼尚不存在 |
| 📋 規格待補 | SDD 僅高層描述，需先寫 TSD 細節再開發 |

## 模組實作狀態（對照 SDD §4）

| 模組 | SDD 職責 | 狀態 | 現有程式 | 缺口摘要 |
|------|----------|------|----------|----------|
| M-001 | Agent 核心、stdin、設定、LLM | 🟡 | `main.py`, `src/agent/planner.py`, `src/utils/config.py`, `llm_client.py`, `io_manager.py` | 無完整多輪 LLM 對話歷史；session 注入 EDA 狀態 + transform 後提示 `check_equivalence` |
| M-002 | Prompt / Schema | 🟡 | `tool_spec.py`, `_SYSTEM_PROMPT` | 15 tools 已暴露；無獨立 Prompt Manager |
| M-003 | Netlist 解析與圖分析 | 🟡 | `engine.py`, `parser/` | regex parser；fanin/fanout cone、critical path 已有；clock domain、完整 path 枚舉、內部信號等價查詢仍缺 |
| M-004 | 轉換與優化 | 🟡 | `insert_buffers`, `replace_gate` | buffer fanout-limit ✅；缺 depth opt、remap、dangling 移除、cone remap 等 |
| M-005 | 形式驗證與容錯 | 🟡 | `check_equivalence` + ABC `cec` | flop-cut combinational CEC ✅；無 SEC、無 counterexample 回饋 LLM |

## Tool 實作狀態（已暴露給 LLM）

| Tool | 狀態 | 後端 |
|------|------|------|
| `load_design` | ✅ | C++ `load` |
| `write_design` | ✅ | C++ `write` |
| `analyze_depth` | 🟡 | C++ `calc_depth`（DFF 邊界待修正） |
| `analyze_critical_path` | 🟡 | C++ `get_critical_path` |
| `find_paths` | 🟡 | C++ `list_paths`（枚舉上限 100；部分 prompt 句式 verify 尚未 dispatch） |
| `count_fanin_gates` | ✅ | C++ `count_fanin` |
| `count_fanout_gates` | ✅ | C++ `count_fanout` |
| `get_fanin_cone` | 🟡 | C++ `get_fanin_cone` |
| `get_fanout_cone` | 🟡 | C++ `get_fanout_cone` |
| `get_fanin_depth` | 🟡 | C++ `get_fanin_depth` |
| `get_node_info` | ✅ | C++ `get_info` |
| `list_nodes` | ✅ | C++ `list_nodes` |
| `count_gates` | 🟡 | C++ `count_gates`（XNOR 等待確認） |
| `insert_buffers` | 🟡 | C++ `insert_buffers`（fanout ≤ N；test21 verify PASS + ABC EQUIVALENT） |
| `check_equivalence` | 🟡 | parser `write_blif` + ABC `cec`（flop-cut；transform 邊界） |
| `replace_gate` | 🟡 | C++ `replace_gate`（僅改 gate type） |

## 設計約束合規狀態（對照 SDD §2.2）

| 約束 | 狀態 | 備註 |
|------|------|------|
| read/write 60s 上限 | ⬜ | 尚未在程式 enforce |
| 其他操作 300s 上限 | 🟡 | ABC 呼叫有 300s timeout |
| LLM 模型 / 參數 | ✅ | `config.yaml` |
| 禁止評分相關字眼 | 🟡 | system prompt 有要求，無自動檢查 |
| 功能等價保證 | 🟡 | `check_equivalence` + 離線 verify 腳本 ABC；非完整 pipeline |

## 分支整合狀態（2026-06-16）

本地 **`main`** 已合併以下遠端分支（**尚未 push** 至 `origin/main`，ahead 21 commits）：

| 分支 | 狀態 | 帶入內容 |
|------|------|----------|
| `origin/parser_try` | ✅ 已包含 | C++ parser、Python 整合、早期 test01/02 |
| `origin/feat/cross-platform-and-session-state` | ✅ 已包含 | 跨平台 build、session state |
| `origin/feat/project-restructure` | ✅ FF 合併 | `src/` 目錄、SDD/docs、CI、Docker |
| `origin/feat/buffer-insertion` | ✅ merge `656f639` | buffer insert、ABC CEC、`write_blif`；含 `test 6~8 OK` 等 commit |

**無未合併的上述 feature 分支。** 其餘遠端僅 `origin/main`（舊）與本地 `main`（新）之差異。

---

## 驗證與測資覆蓋（2026-06-16）

使用 `scripts/verify_testcases.py`（見 [VERIFICATION.md](./VERIFICATION.md)）。  
離線 verify **不等於** 競賽評分；LLM 路徑（`main.py`）可能跑通 verify 標 PARTIAL 的 step。

### 離線 verify 基線

| 範圍 | Case 結果 | 備註 |
|------|-----------|------|
| tier `smoke`（test01–02） | 2 PASS | 全 step PASS |
| tier `basic`（test01–08） | 6 PASS, 2 PARTIAL | test07/08：path 句式 dispatch 缺口 |
| test01–06（`audit-test01-16` run） | 6 PASS | 見 `verification_runs/20260616_143927_audit-test01-16/` |
| test07–11（同上 run，未完成 12–16） | 5 PARTIAL | 皆為 path 枚舉/連接句式 → UNSUPPORTED |
| test21（buffer） | 1 PASS | insert + write + ABC EQUIVALENT |

### Path 相關：engine vs verify 腳本

C++ **`list_paths`**（`find_paths` tool）已合併進 main。例如 test07 **L4**（`from n0[0] to n5 … avoiding n95`）verify **PASS** 且可列 path。

下列 **prompt 句式** 在 verify 中仍為 **UNSUPPORTED**（`verify_lib.py` regex 未覆蓋，**不代表 engine 缺功能**）：

- `Verify whether a path connecting input … to output … while avoiding …`
- `List every path originating at primary input … and terminating at …`
- `Provide a complete enumeration of paths between … and …`

`parser_try` 地端 test01–16 可跑通：與上述一致（parser 已在 main；verify 規則待補）。

**目標：** 隨實作與 verify dispatch 擴充提高 PASS case 數；PARTIAL 需區分「缺功能」vs「腳本未 dispatch」；FAIL 優先修。

## 後續規劃 Tool / 能力（尚未暴露或未完整）

- Technology remap（NAND/NOT basis 等）— test25+
- Depth / critical-path optimization — test22+
- Dangling / unused gate removal — test23+
- 內部信號等價、Boolean equation、constant detection — test31+
- Register-to-register path — test32+
- 完整 path 枚舉（無 100 上限或 grader 對齊）— test09–20

細節規格見 [TSD.md](./TSD.md)；逐 case 對照見 repo 根目錄 `testcase_analysis.md`。

## 版本歷程

| 版本 | 日期 | 修改人 | 摘要 |
|------|------|--------|------|
| v0.1 | 2026-06-10 | — | 初版，對照 SDD v0.2 |
| v0.2 | 2026-06-16 | — | 合併 project-restructure + buffer-insertion；15 tools、ABC CEC、verify 腳本基線 |
| v0.3 | 2026-06-16 | — | 四分支整合狀態；test01–11 audit；path verify dispatch 缺口說明 |

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
| M-001 | Agent 核心、stdin、設定、LLM | 🟡 | `main.py`, `planner.py`, `config.py`, `llm_client.py`, `io_manager.py` | 無完整多輪 LLM 對話歷史；僅注入 EDA session 狀態 |
| M-002 | Prompt / Schema | 🟡 | `tool_spec.py`, `_SYSTEM_PROMPT` | 無獨立 Prompt Manager；使用 LLM function calling |
| M-003 | Netlist 解析與圖分析 | 🟡 | `engine.py`, `parser/` | regex parser（非 AST）；無 clock domain / logic cone；depth/path 未切 DFF |
| M-004 | 轉換與優化 | 🟡 | `replace_gate` only | 缺 buffer insert、depth optimize、dangling 移除、cone remap |
| M-005 | 形式驗證與容錯 | ⬜ | — | 缺 CEC/SEC、original 備份、counterexample 回饋 |

## Tool 實作狀態（Phase 1 已暴露）

| Tool | 狀態 | 後端 |
|------|------|------|
| `load_design` | ✅ | C++ `load` |
| `write_design` | ✅ | C++ `write` |
| `analyze_depth` | 🟡 | C++ `calc_depth`（DFF 邊界待修正） |
| `find_paths` | 🟡 | C++ `count_paths`（回傳數量，非完整枚舉） |
| `get_node_info` | ✅ | C++ `get_info` |
| `list_nodes` | ✅ | C++ `list_nodes` |
| `count_gates` | 🟡 | C++ `count_gates`（XNOR 統計待修正） |
| `replace_gate` | 🟡 | C++ `replace_gate`（僅改 gate type） |

## 設計約束合規狀態（對照 SDD §2.2）

| 約束 | 狀態 | 備註 |
|------|------|------|
| read/write 60s 上限 | ⬜ | 尚未在程式 enforce |
| 其他操作 300s 上限 | ⬜ | 尚未在程式 enforce |
| LLM 模型 / 參數 | ✅ | `config.yaml` |
| 禁止評分相關字眼 | 🟡 | system prompt 有要求，無自動檢查 |
| 功能等價保證 | ⬜ | 無自動 verify pipeline |

## 後續規劃 Tool（SDD 目標，尚未暴露給 LLM）

以下能力在 SDD 架構圖 / M-004、M-005 中已規劃，**尚未**加入 `tool_spec.py`：

- `verify_equivalence_vs_original`（ABC CEC/SEC）
- `insert_buffer_fanout_limit`
- `optimize_critical_path_depth`
- `enumerate_all_paths`（含 limit / timeout）
- clock domain / fanin cone 系列查詢

細節規格請在 [TSD.md](./TSD.md)（待建立）中定義 API 與演算法後再實作。

## 版本歷程

| 版本 | 日期 | 修改人 | 摘要 |
|------|------|--------|------|
| v0.1 | 2026-06-10 | — | 初版，對照 SDD v0.2 |

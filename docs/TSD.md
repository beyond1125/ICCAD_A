# 技術規格文件（TSD）

本文件描述 **API、演算法與資料結構** 細節。  
已實作段落標 ✅；待實作標 📋。

## 與 SDD / IMPLEMENTATION_STATUS 的分工

| 文件 | 回答的問題 | 讀者 |
|------|------------|------|
| [SDD.md](./SDD.md) | 系統要做什麼、模組怎麼分 | 全員、評審 |
| **TSD.md（本文件）** | 怎麼做（API、演算法） | 開發者 |
| [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) | 哪些已做、哪些還沒做 | 全員 |
| [VERIFICATION.md](./VERIFICATION.md) | 怎麼驗證、log 在哪 | 開發、merge |

---

## 1. C++ Parser CLI ✅

```
parser_cpp --in <file.v> --action <action> [--key value ...]
```

常用 action：`load`, `write`, `calc_depth`, `list_paths`, `get_info`, `list_nodes`, `count_gates`, `replace_gate`, `count_fanin`, `count_fanout`, `get_fanin_cone`, `get_fanout_cone`, `get_fanin_depth`, `get_critical_path`, `insert_buffers`, `write_blif`。

Python 橋接：`src/eda_engine/engine.py` → subprocess。

Transform 後 session 檔鏈：`_loaded_filepath` 指向最新 `_out.v`，`load_design` 時保留 `_original_filepath` 供等價驗證。

---

## 2. ABC 等價驗證（flop-cut CEC）✅

**Tool：** `check_equivalence(reference: optional)`

**流程：**

1. `reference` 預設為 `_original_filepath`（load 當下 netlist）。
2. 對 current 與 reference 各執行 parser `write_blif` → 暫存 `.blif`。
3. **BLIF 模型：** 每個 DFF 的 Q → primary input；D → output `__D_<inst>`（combinational shell）。
4. 執行：`abc -q "cec <ref.blif> <cur.blif>"`（timeout 300s）。
5. 解析：`are equivalent` / `not equivalent`。

**適用：** buffer insertion、單純 gate type 替換等 **不改 DFF 邊界語意** 的 transform。  
**不適用 / 未驗證：** 改 flop 行為、sequential 等價（需 SEC / 更完整 model）。

**二進位解析：** `ABC_BIN` → `tools/abc/abc` → `abc/abc`。

---

## 3. Buffer insertion ✅

**Tool：** `insert_buffers(max_fanout: int = 4)`

**C++ action：** `insert_buffers --max_fanout N --out <file.v>`

**語意：** 插入 BUF，使每個 gate 的 fanout ≤ N；功能透明。成功後 engine 將 `_loaded_filepath` 切到輸出檔。

**驗證：** test21 — verify step PASS + ABC EQUIVALENT（見 VERIFICATION.md 基線）。

📋 **未實作變體：** 單一 signal 上 per-load 專用 buffer（test31 等 prompt）、fanout 以外的 depth balance。

---

## 4. Path 查詢 🟡

**Tool：** `find_paths(start, end, avoid?)` → C++ **`list_paths`**

- `from X to Y avoiding Z` 句式：已實作；test07 L4 verify PASS。
- 枚舉 hard cap **100 paths**。
- verify 腳本尚未 dispatch 的句式（`connecting input…`、`originating at…`、`complete enumeration between…`）見 [VERIFICATION.md](./VERIFICATION.md) §8。

📋 **待補：** grader 對齊的 limit/timeout、更多自然語言句式覆蓋。

---

## 5. 待撰寫章節 📋

1. Technology remap（AND+NOT / NAND+NOT / NOR+NOT basis）
2. Depth / critical-path optimization（含 target depth ≤ 4）
3. Dangling / unused / floating gate sweep
4. 內部信號 combinational 等價（非 whole-design CEC）
5. Boolean equation、constant-0 判定、PI/PO 寬度列表
6. Register-to-register path depth
7. DFF D-pin enable/hold 結構偵測

參考 transform 需求：`partC.md`、`testcase_analysis.md`。

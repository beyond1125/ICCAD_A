# 測資驗證與合併輔助（Verification）

本文件說明 **`scripts/verify_testcases.py`** 的用途、log 放置位置，以及 merge 前後如何比對結果。

> 程式入口：`scripts/verify_testcases.py`（CLI）  
> 共用邏輯：`scripts/verify_lib.py`（勿直接執行）  
> Merge 包裝：`scripts/merge_and_verify.sh`

---

## 1. 目的

- 在 **不呼叫 LLM API** 的前提下，用規則將 `testcase/testNN/prompt.txt` 每一行對應到 EDA tool。
- **逐步（step 級）** 記錄 PASS / FAIL / UNSUPPORTED，方便定位「哪個 testcase、第幾行 prompt」出問題。
- Transform 後以 **ABC `cec`**（flop-cut BLIF）檢查功能等價。
- 作為 **merge 前後回歸檢查**：PASS step 不應減少、FAIL step 不應增加。

---

## 2. 快速開始

```bash
python3 scripts/build_parser.py

# 預設 tier=smoke（test01–02）
python3 scripts/verify_testcases.py -v

# 常用範圍
python3 scripts/verify_testcases.py --tier basic -v --label my-check

# test01–16 逐步 log（--from/--to 與 --tier 互斥）
python3 scripts/verify_testcases.py --from test01 --to test16 -v --no-build --label audit-test01-16

# 單一 case
python3 scripts/verify_testcases.py --case test21 -v

# 只看 prompt 行號
python3 scripts/verify_testcases.py --show-prompts test08
```

---

## 3. Tier 預設

| Tier | Cases | 用途 |
|------|-------|------|
| `smoke`（**預設**） | test01–02 | merge 後快速 smoke |
| `basic` | test01–08 | 分析 + 簡單 path |
| `analysis` | test01–14 | 進階分析 |
| `transform` | test21, 22, 23, 40 | buffer / opt / remap |
| `all` | test01–40 | 全量 |

---

## 4. Step 狀態定義

| 狀態 | 意義 | 是否呼叫 engine |
|------|------|-----------------|
| **PASS** | tool 執行成功 | 是 |
| **FAIL** | tool 報錯、ABC 失敗、缺 output | 是 |
| **UNSUPPORTED** | 無 dispatch / 缺 tool / 參數解析失敗 | **否** |
| **SKIP** | testcase init 行 | 否 |

**Case 級：** 無 FAIL 且無 UNSUPPORTED → **PASS**；有 UNSUPPORTED → **PARTIAL**；有 FAIL → **FAIL**。

> UNSUPPORTED 常見原因：① verify regex 未覆蓋句式（engine 已有 tool，見 §8）② 功能未實作。

---

## 5. Log 放在哪裡

**根目錄：`verification_runs/`**（gitignore）

```
verification_runs/YYYYMMDD_HHMMSS_<label>/
├── ISSUES.md       ← 【先看】僅 FAIL / UNSUPPORTED
├── SUMMARY.md      ← case 總表
├── steps.csv       ← 全部 step
└── testNN/
    ├── report.md   ← 每行 prompt 的 tool + engine 回傳
    └── abc/        ← transform 時：equivalence.log, *.blif
```

閱讀順序：**ISSUES.md** → **SUMMARY.md** → **testNN/report.md**。

競賽執行的 `testcase/testNN/testNN.log`、`*_out.v` 與本 verify log 分開存放。

---

## 6. Merge 前後比對

```bash
VERIFY_TIER=smoke ./scripts/merge_and_verify.sh origin/feat/<branch>
```

比對 `verification_runs/*_before-*/ISSUES.md` 與 `*_after-*/ISSUES.md`。  
分支整合現況見 [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) §分支整合。

---

## 7. 目前驗證基線（2026-06-16）

| 範圍 | 結果 | 備註 |
|------|------|------|
| smoke（test01–02） | 2 PASS | |
| basic（test01–08） | 6 PASS, 2 PARTIAL | test07/08 |
| test01–06 | 6 PASS | `verification_runs/20260616_143927_audit-test01-16/` |
| test07–11 | 5 PARTIAL | path dispatch；test12–16 同 run 中斷 |
| test21 | PASS + ABC EQUIVALENT | buffer |

---

## 8. 已知 verify dispatch 缺口（path）

**`find_paths` / C++ `list_paths` 已在 main。** test07 L4（`from … to … avoiding …`）verify PASS。

下列句式仍 UNSUPPORTED（需擴 `verify_lib.py`）：

| 句式 | verify |
|------|--------|
| `connecting input … to output … while avoiding …` | ❌ |
| `originating at primary input … terminating at …` | ❌ |
| `complete enumeration of paths between A and B` | ❌ |

協作者地端 test01–16 若用 **`main.py` + LLM**，不受上述 regex 限制。

---

## 9. 與其他測試的關係

| 方式 | 路徑 | 差異 |
|------|------|------|
| 整合測試 | `tests/integration_tests/run_test.py` | test8 I/O 協定 |
| 煙霧測試 | `tests/unit_tests/verify_integration.py` | 無 assert |
| **本驗證** | `scripts/verify_testcases.py` | 批次 prompt.txt；step 級；ABC |

CI 目前只跑 integration test；可擴充 `--tier smoke --strict`。

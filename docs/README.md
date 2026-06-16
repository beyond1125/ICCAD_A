# 文件目錄

| 文件 | 類型 | 說明 |
|------|------|------|
| [SDD.md](./SDD.md) | 系統設計文件 | 系統目標、架構、模組劃分、目錄與 I/O 協議 |
| [TSD.md](./TSD.md) | 技術規格文件 | 已實作與待實作功能的 API、演算法細節 |
| [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) | 實作狀態 | SDD 規劃 vs 程式現況、測資 verify 基線 |
| [VERIFICATION.md](./VERIFICATION.md) | 驗證與 merge | `verify_testcases.py`、log 位置、tier、merge 比對 |

###  repo 根目錄補充（非 docs/）

| 文件 | 說明 |
|------|------|
| [testcase_analysis.md](../testcase_analysis.md) | 40 個 official testcase 各 prompt 所需 tool 對照 |
| [partC.md](../partC.md) | Transform 工程師工作範圍與 T-code 對照 |

### 文件維護原則

- **SDD 變更**（新增模組、修改 I/O 協議）→ 更新 SDD，並同步 IMPLEMENTATION_STATUS。
- **開始實作某 SDD 功能前** → 先在 TSD 寫清接口與演算法，再寫 code。
- **功能 merge 後** → 更新 IMPLEMENTATION_STATUS；跑 `verify_testcases.py` 更新 VERIFICATION 基線表。
- **新增 verify tier / log 格式** → 更新 VERIFICATION.md。

### 建議閱讀順序（新成員）

1. [SDD.md](./SDD.md) §1–3 — 系統在做什麼  
2. [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) — 做到哪、**哪些 branch 已合併**  
3. [VERIFICATION.md](./VERIFICATION.md) — 怎麼跑測資、log 在哪、path dispatch 缺口  
4. [testcase_analysis.md](../testcase_analysis.md) — 下一個要解哪個 testNN  

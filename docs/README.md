# 文件目錄

| 文件 | 類型 | 說明 |
|------|------|------|
| [SDD.md](./SDD.md) | 系統設計文件 | 系統目標、架構、模組劃分、**已實作**的目錄與 I/O 協議 |
| [TSD.md](./TSD.md) | 技術規格文件 | **未實作**功能的 API、演算法與資料結構（待撰寫） |
| [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) | 實作狀態 | SDD 規劃 vs 程式現況的追蹤表 |

### 文件維護原則

- **SDD 變更**（新增模組、修改 I/O 協議）→ 更新 SDD，並同步 IMPLEMENTATION_STATUS。
- **開始實作某 SDD 功能前** → 先在 TSD 寫清接口與演算法，再寫 code。
- **功能 merge 後** → 更新 IMPLEMENTATION_STATUS 狀態；若行為穩定，將細節回寫 SDD 或 TSD。

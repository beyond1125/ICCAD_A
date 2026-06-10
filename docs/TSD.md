# 技術規格文件（TSD）

> **狀態：待建立**  
> 本文件用於描述 SDD 中 **已規劃但尚未實作** 功能的技術細節。

## 與 SDD / IMPLEMENTATION_STATUS 的分工

| 文件 | 回答的問題 | 讀者 |
|------|------------|------|
| [SDD.md](./SDD.md) | 系統要做什麼、模組怎麼分 | 全員、評審 |
| **TSD.md（本文件）** | 未實作功能怎麼做（API、演算法、資料結構） | 開發者 |
| [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) | 哪些已做、哪些還沒做 | 全員、PM |

## 待撰寫章節（建議）

1. C++ Graph 資料結構與 DFF 邊界規則
2. Tool API 完整定義（參數、回傳格式、錯誤碼）
3. ABC 等價驗證流程（combinational / sequential）
4. Transform 演算法（buffer insertion、depth optimization）
5. `enumerate_all_paths` 的 limit / timeout 策略

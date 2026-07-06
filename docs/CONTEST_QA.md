# 官方 Q&A 摘要(A_QA_20260703.pdf)

主辦方(Cadence)對 Problem A 的官方答覆,2026-07-03 版。原始 PDF 在專案根目錄
`A_QA_20260703.pdf`(紅字刪改線為主辦方自己的修訂,以修訂後為準)。
本檔為結構化摘要 + 對本專案的影響對照;規格衝突時以本檔(官方答覆)為準,
再來才是 `A_20260212.pdf` 與 `docs/OPEN_QUESTIONS.md` 的自訂決策。

## ⚠ 需要行動的答覆(對照 docs/PLAN_QA_fixes.md)

| # | 官方答覆 | 對本專案的影響 |
|---|---|---|
| A5.1+A6.1(修訂) | **Docker 交付不支援**。程式必須能在 TSRI 機器直接執行;PyInstaller 等自包式打包可接受。評測時網路**只開放 model API**,不能 pip install | 現行 Dockerfile 交付路線作廢(保留為開發工具);需改為 TSRI 直跑的自包式打包(P0) |
| A5.3 | 所有輸入/輸出檔案路徑**相對於工作目錄** | io_manager 的 CWD log ✓ 已合規;但 system prompt 硬編碼 `testcase/<case>/` 路徑指引,對 hidden prompts 危險(P0) |
| A6.2 | **最終評測有隱藏 prompts**,不要只做文件列舉的工具功能 | 支持既有的泛化方向(任意 basis 分解等);路徑假設必須去硬編碼 |
| A16 | 「list all X」大結果:**期望完整清單寫入檔案並在回應中給出檔案路徑** | `_truncate_large_result` 的 saved_to_file 設計被官方背書 ✓;但 `find_all_paths` 的 10k 收集上限會使檔案內容不完整,需改為完整枚舉流式落檔(P1) |
| A5.6 | 輸入 netlist **可能有 floating / unconnected ports** | 需驗證 parser 容錯(P2);`list_floating` 工具已存在 |
| A14.2 | 評測**不會**用固定 seed / temperature=0 | 非確定性是常態;多次執行變異性值得量測(P2) |

## ✓ 確認合規/背書的答覆

| # | 官方答覆 | 本專案狀態 |
|---|---|---|
| A1 | 測資 gate 例項一定有名字 | parser 的 anon_N 分支只是保險 ✓ |
| A2 | 只會有內建 primitive 關鍵字(無 標準元件庫 cell) | parser 假設成立 ✓ |
| A12 | **testcase 的 dff(含 .SN active-low set)才是對的**,spec 的 4-port 定義過時 | 我們早已按 testcase 處理 pin_conns ✓ |
| A13 | OpenAI API 全相容;**評測時主辦方換上自己的 key/config** | `Config.from_yaml` 對字面 key 與 `${VAR}` 皆相容 ✓ |
| A14.1/3/4 | 分析題評分 = **LLM-as-a-judge 語意等價**,措辭不同拿全分 | 不需 exact-match 措辭;check_answers 的語意抽取方向正確 ✓ |
| A15 | 允許第三方 binary(如靜態 ABC),無大小限制 | ABC 隨包合法 ✓ |
| A18 | rate limit 依模型政策;**無 token 上限**;60s/300s 時限確認 | 時間預算階層(270/180/150)合規 ✓;retry 設計合理 ✓ |
| A11 | 兩個 LLM 各算獨立成績 | Haiku 40/40 已證;4o-mini 待 key 有額度後驗證 |
| A19 | 不提供官方評分工具 | 自建四層評估是正確投資 ✓ |
| A20 | 最終評測含隱藏測資 | 同 A6.2 |

## 資訊性

- A3/A5.5:公開測資已釋出(即 testcase/test01–40)。
- A4:評測模型 = ChatGPT 4o mini + Claude 4.5 Haiku,只能走 API,不可微調。
- A7:開發期用自己的 key。
- A8/A9:優化題的 cost **定義在 prompt 裡**(逐題讀 prompt 決定目標函數)。
- A10:EDA 後端工具不限(可用 Yosys/商用工具);我們的自建引擎 + ABC 合法。
- A17:RAM/磁碟限制參考 TSRI 機器規格(規格文件未附)。

## A21(使用者提供補充,PDF 渲染缺漏)— 三個未決項全部落槌

| # | 官方裁決 | 對既有決策的影響 |
|---|---|---|
| A21.1 | 「constant」= **功能恆定**(對所有輸入可證恆 0/1);**DFF 初始態 = 0**,X 忽略 | **推翻 O6 的結構性解讀** — 現行 `const_propagate` 只認結構上綁 1'b0/1'b1;「always 0?」「report gates with constant input」類問題需要 SAT 級功能恆定分析 + DFF-init-0 的時序常數語意(PLAN P1-8) |
| A21.2 | cone/深度 = **僅組合邏輯**,DFF.Q 視為 primary input | **確認 O1**(深度 flop 邊界 ✓,引擎與 oracle 已對齊);**挑戰 D4** — 分析類 cone 問題應以組合 cone 作答(oracle 已是此預設 ✓,引擎的 cone 分析工具穿越 DFF,需對齊,PLAN P2-9);transform 用的穿越式 cone 因等價性安全暫維持 |
| A21.3 | complete enumeration = **逐條列出**;超大結果寫檔 + 回應附路徑 | 與 A16 一致,**P1-3(流式落檔完整枚舉)升為必要項** |
| A21.4 | 功能等價是主要評分;次要指標會在 prompt 明示;多種合法改寫時 prompt 會指明優化準則 | 等價優先架構 ✓;cost 逐題讀 prompt(同 A8/A9) |
| A21.5/6 | **只允許單執行緒、一次一個請求**;rate limit 依模型政策、無 token 上限;60s/300s;硬體看 TSRI 規格 | 現行架構已合規(planner 順序執行、subprocess 依序、ABC 單執行緒);**不變量:未來不得加平行工具執行**(記入 agent-runtime 規則,PLAN P2-9 一併) |

**維護規則**:官方釋出新版 QA 時,更新本檔並在 PLAN/OPEN_QUESTIONS 同步標註;
本檔結論與程式行為衝突時,依 `.claude/rules/docs-sync.md` 的紀律同 commit 修正。

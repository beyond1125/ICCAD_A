# 修復計畫:官方 Q&A(2026-07-03)衝擊項

> 狀態:**執行中**(2026-07-07 擬定,依據 docs/CONTEST_QA.md)。
> 已完成:P1-4 + P1-5(2026-07-07, a979281)、P0-2(2026-07-08, 831c97e)、
> P0-1(2026-07-08, 4c6d765)、P1-3(2026-07-11)、P1-8(2026-07-11)。
> 待做:P2-9、P2-6、P2-7(可選),收尾全量 sweep + 四層驗證。

## P0-1 交付打包改道:廢 Docker、改 TSRI 直跑自包式(A5.1/A6.1)

**問題**:Docker 交付不支援;評測機只開 model API 網路,不能 pip install。
現行交付故事(Dockerfile)整條作廢。

**方案**(建議 a,備選 b):
- (a) **Vendored 目錄包**:交付一個自包目錄 — `python3 -m venv` 打進包裡
  (`pip install -r requirements.txt` 於打包機完成)、預編譯 `parser_cpp`、
  靜態建置的 ABC binary、`cada1066_alpha` wrapper 改為指向包內 venv 的
  python。風險低、除錯容易;前提:TSRI 機器有相容的 glibc/Python(A17 要查
  TSRI 規格)。
- (b) PyInstaller 單檔:更自包,但 anthropic/openai SDK 的動態 import 打包
  相容性需實測,風險較高。
- 共通:打包腳本 `scripts/package_submission.py` 產出 `cada1066_alpha/` 交付
  目錄 + 冒煙測試(在乾淨路徑解包 → 跑 test02 全流程)。Dockerfile 降級為
  「開發環境重現工具」,README/TSD §9 同步改寫。

**驗證**:乾淨 shell(清空 PATH 干擾、無 repo 環境)解包執行
`./cada1066_alpha -config config.yaml` 跑 test02 三層驗證全過。
**工作量**:中(1 個 subagent 任務 + 打包機驗證)。

## P0-2 去除路徑硬編碼(A5.3/A6.2 hidden prompts)

**問題**:`planner.py` system prompt 寫死「Designs are located in
testcase/<case_name>/」「ALWAYS save to the same testcase directory」。
隱藏測資的路徑慣例未知(spec 範例是 `design/netlist/`),硬編碼會答錯路徑。

**方案**:system prompt 改為:「用請求中明示的路徑(相對工作目錄);寫出時
用請求指定的檔名/路徑;請求沒給目錄時,寫到與載入設計相同的目錄」。
`io_manager` 不動(CWD log 已合規)。
**風險**:改 system prompt 影響全部 40 題行為 → 必須全量回歸。
**驗證**:全量 sweep + check_results 40/40 不退步;另造 1 個「非 testcase
路徑」的合成 prompt(模仿 spec 的 design/netlist/ 例)驗證讀寫路徑正確。
**工作量**:小改 + 全量回歸(~1hr sweep)。

## P1-3 list_paths 完整枚舉流式落檔(A16)— ✅ 完成(2026-07-11)

> 實作與計畫一致,另加:流式模式資源上限(10^6 條/512MB,觸頂時 header 標
> INCOMPLETE + DP 精確總數 — 無上限時病態配對會在 150s timeout 前寫出數十
> GB);`count_paths` DP 改 64 位元飽和加法;修復 Python header regex 在
> capped 輸出上不匹配的既有 bug。驗證:test14 289,366 條完整落檔(行數 ==
> DP 值,1.9s);test02/08/12/14 LLM 回歸 OK + 等價 PASS,path 類答案全
> CORRECT。

**問題**:A16 要求「完整清單寫檔 + 回應給路徑」。現行 `find_all_paths` 有
10k 收集上限(防爆記憶體),超過的枚舉檔案不完整;test14 級別(289k 條)
需要能交出完整檔案。

**方案**:C++ `list_paths` 加 `--paths_out <file>` — 枚舉時**流式寫檔**
(找到一條寫一條,不進記憶體向量),移除記憶體收集對完整性的限制;stdout
保持首行 `Found N paths`(N=DP 精確值)+ 檔案路徑 + 前 100 條預覽。
10k cap 保留給「無 --paths_out」的舊行為。Python `engine.find_paths` 帶
session 檔名呼叫並在工具結果附 `saved_to_file`(沿用既有慣例,agent 已被
system prompt 訓練成會提及該路徑)。
**驗證**:test14 的 289k 條枚舉落檔完整(行數 == count_paths DP 值)、
test12/test08 行為不退步;耗時仍在 150s 動作上限內(流式寫 289k 行 ≈ 秒級)。
**工作量**:中(C++ + engine + 文件同步)。

## P1-4 fanout 語意澄清(答案報告的 DIVERGENT 群:test12/15/17/18/19)

**問題**:「number of gates driven by X」agent 一律答遞移錐(工具
`count_fanout_gates` 的名字誤導),自然語意應為直接驅動。

**方案**:tool_spec 兩個工具描述改寫 —「direct loads 用 get_node_info 的
Driven Gates / fanout_count;transitive cone 用 count_fanout_gates」;
system prompt KEY RULES 加一行:「'gates driven by X' / 'fanout of X' 指
**直接**驅動的 gate,除非題目明說 transitive/cone」。
**驗證**:重跑 test12/15/17/18/19 五題,answer report 的 fanout 類
DIVERGENT → CORRECT,其餘不退步。
**工作量**:小。

## P1-5 path-avoid 真錯修復(test13/16 ×3 WRONG)

**問題**:find_paths 回 0 條時,agent 仍答「yes 存在路徑」(捏造肯定句,
answer-gate 攔不到 — 有呼叫工具、只是無視結果)。

**方案**:system prompt KEY RULES 加:「path 存在性問題:find_paths 回報
0 條或 'No paths found' 時,答案必須是 No」。若 prompt 規則不夠(小模型
遵循度),備選:engine.find_paths 在 0 條時於結果字串前置
`ANSWER: NO —`(把結論寫進工具輸出,agent 抄結論的傾向反而變成助力)。
**驗證**:重跑 test13/16,三個 WRONG → CORRECT;test06-20 的 path 類
CORRECT 不退步。
**工作量**:小。

## P1-8 功能恆定分析(A21.1 — 推翻 O6 的結構性解讀)— ✅ 完成(2026-07-11)

> 落地紀錄:`check_const` 工具 + `const_propagate --semantics functional`
> 依方案 (i)(ii) 實作(C++ 新 action:`report_stuck_inputs`/`sim_consts`/
> `write_cone_blifs`/`list_dffs`/`tie_nets_const`;engine 預算 110s/80s/20s)。
> 效能修復:`run_random_sim` 原以逐拍 unordered_map 實作,test39(5.6MB)
> 單次掃描 ~90s 導致整案 900s TIMEOUT;改為稠密槽位編譯後 ~5s(輸出逐位元
> 組相同),test39 481s OK。驗證:test31 Q8 vs oracle `always_const` 一致
> (皆非恆定);test32/36/38/39/40 重跑全 PASS+EQUIV(test36/38/40 由 7/3
> 基線的 GOAL-FAIL 轉 PASS);check_results 40/40 無硬性違規;test39 OR
> stuck=1 候選抽 4 網 oracle 皆 None,與「0 可證明+10 未證明」的誠實回答
> 一致。後續升級路徑(pdr/scleanup 精確時序證明)見 chip「Add sequential
> BLIF export; wire scleanup/pdr into check_const」。

**問題**:官方裁決「constant」= 功能恆定(SAT 可證恆 0/1),DFF 初始態 = 0、
X 忽略。現行 `const_propagate` 只認結構上綁 1'b0/1'b1;受影響題型:
「Is output n16 always 0?」(test31)、「Report any AND/NAND/OR/NOR gates with
constant inputs」+ 對應 simplify(test32/36/38/39/40)— 結構性回答可能漏報
功能恆定的訊號。

**方案**(兩階段):
- (i) 新引擎工具 `check_const(net)`:對單一網的組合 cone 用自製 BLIF + ABC
  SAT 判恆 0/恆 1(oracle 的 `always_const` 已有同款實作可移植),疊加
  **DFF-init-0 定點迭代**:先假設全部 DFF.Q 未知 → 凡 D 端可證恆 0 的 DFF
  其 Q 視為常數 0 → 重跑直到不動點(時序常數掃描的保守近似,DFF 初始態 0
  下是健全的)。
- (ii) `const_propagate` 加 `--semantics functional` 模式:report 時對每個
  gate 的每個輸入網跑 (i) 的判定(以 cone 大小上限與快取控制成本);
  simplify 沿用結構性傳播(功能恆定的輸入以 (i) 證明後綁常數再傳播,
  等價性由 cec 把關)。
**驗證**:test31 Q8 的 always-0 答案與 oracle `always_const` 一致;
test32/36/38/39/40 的 const 報告題重跑,answer report 不退步;全部轉換後
cec 等價維持。
**工作量**:大(本計畫最大項;ABC SAT 批次成本需實測)。

## P2-9 分析 cone 語意對齊 + 單執行緒不變量(A21.2/A21.5)

**問題**:A21.2 裁決分析類 cone/深度僅組合邏輯(DFF.Q = PI)。oracle 預設
已正確;引擎的 cone 分析工具(get_fanin_cone/count_fanin_gates/
count_gates_in_cone)穿越 DFF(D4 的 transform 慣例外溢到分析)。
**方案**:C++ cone 分析加 `--stop_at_dff`(預設開啟於分析類 action);
transform 用的 `fanin_cone_gates` 維持穿越(等價性安全,D4 理由仍成立)。
tool_spec 描述同步說明語意。OPEN_QUESTIONS D4/O1/O6 加官方裁決註記。
另:A21.5「僅單執行緒」寫入 `.claude/rules/agent-runtime.md` 作為不變量
(禁止未來加平行工具執行)。
**驗證**:cone 類分析答案 vs oracle(combinational)全 40 題比對;
transform 題等價性不退步。
**工作量**:中。

## P2-6 floating/unconnected ports 容錯(A5.6)

**方案**:造 3 個合成 fixture(懸空輸入、未接輸出 port、未驅動 wire),
驗證 parser 載入不崩潰、list_floating 正確回報、write 回寫不丟資訊;
發現問題再修。
**工作量**:小(測試先行)。

## P2-7 非確定性變異量測(A14.2)

**方案**(可選):同一題跑 3 次,量 answer report 的判定漂移,建立
「單次 sweep 結果的置信度」概念;不改 runtime。
**工作量**:小,燒 API。

## 建議執行順序與 subagent 切分

1. P1-4 + P1-5(同一個 subagent:都是 prompt/tool_spec 小改,共用一次
   五題回歸)
2. P0-2(獨立 subagent;需全量 sweep 回歸,等 1 完成避免混淆歸因)
3. P1-3(獨立 subagent:C++ + engine + docs;A21.3 後為必要項)
4. P0-1(獨立 subagent:打包;與 2/3 無程式碼衝突,可並行)
5. **P1-8(獨立 subagent,最大項)**:功能恆定分析;建議在 1–3 落地後做,
   因為它會改動 const 類題的答案語意,需要乾淨的回歸基準
6. P2-9(獨立 subagent:cone 語意 + 單執行緒不變量文件化)
7. P2-6(小 subagent)、P2-7(可選)

全部完成後:全量 sweep + 四層驗證 + 更新 CONTEST_QA.md 的狀態欄。

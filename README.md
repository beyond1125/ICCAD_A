# ICCAD 2026 Problem A: LLM-Assisted Netlist Transformation

這是一個結合大型語言模型 (LLM) 與 C++ 後端引擎的電路網表 (Netlist) 處理系統。系統能夠解析 Verilog 網表、分析電路結構（如路徑計數、深度計算）並進行閘級轉換（如更換閘類型）。

## 專案架構

```text
ICCAD_A/
├── main.py              # 系統入口點，負責與使用者/測試環境互動的 Loop
├── io_manager.py        # 處理輸出格式規範 (#RESPONSE) 與 Log 記錄
├── config.py            # 設定檔解析 (YAML & .env)
├── config.yaml          # 系統執行設定 (LLM 模型選擇等)
├── .env                 # API 金鑰存放 (需手動建立，已被 gitignore)
├── requirements.txt     # Python 套件依賴清單
│
├── agent/               # AI 代理人核心
│   ├── planner.py       # 任務規劃器，協調 LLM 與 Tool 呼叫
│   ├── llm_client.py    # LLM API 封裝 (支援 OpenAI/Anthropic)
│   └── tool_spec.py     # 定義暴露給 AI 的工具介面
│
├── eda_engine/          # EDA 引擎封裝
│   └── engine.py        # Python 介面，透過子程序呼叫 C++ Parser
│
├── parser/              # C++ 核心解析器
│   ├── parser.cpp       # Verilog 解析與圖形結構邏輯實作
│   ├── parser.hpp       # 資料結構 (Graph, Node) 定義
│   └── parser_cpp.exe   # 編譯後的執行檔
│
├── testcase/            # 官方測試案例目錄
├── tests/               # 開發驗證用的測試腳本
├── venv/                # Python 虛擬環境 (建議使用)
└── tools/abc            # 自己clone abc到這個資料夾備用
```

## 檔案說明

- **`main.py`**: 核心啟動檔。它會讀取標準輸入，辨識測試案例初始化訊息，並將使用者的自然語言指令交給 AI Planner 處理。
- **`parser/`**: 系統的運算核心。使用 C++ 撰寫以確保解析大型網表（數千個閘）時的效能。支援 Verilog-1995 格式輸出。
- **`eda_engine/engine.py`**: 橋樑模組。它負責將 Python 的指令轉換為 C++ 解析器能理解的參數，並讀取解析後的結果。
- **`agent/planner.py`**: 決策大腦。它將使用者的意圖轉化為一系列的工具呼叫（如：先 load\_design 再 analyze\_depth）。
- **`io_manager.py`**: 嚴格遵循競賽規範的輸出管理器，自動處理 `#RESPONSE` 標籤與時間戳記 Log。

## 環境建置

1. **建立虛擬環境並安裝套件**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **編譯 C++ Parser**:
   ```bash
   g++ -std=c++17 parser/parser.cpp -o parser/parser_cpp.exe
   ```

3. **設定 API 金鑰**:
   建立 `.env` 檔案並填入您的金鑰：
   ```text
   ANTHROPIC_API_KEY=your_key_here
   OPENAI_API_KEY=your_key_here
   ```

4. **clone abc到tools資料夾備用**
   ```bash
   cd tools
   git clone https://github.com/berkeley-abc/abc.git
   cd abc
   make
   ```
   **使用方式**
   ```bash
   ./abc
   ```

## 執行方式

啟動主程式：
```bash
python main.py -config config.yaml
```
啟動後，您可以直接在終端機輸入自然語言指令，例如：
*   `Initialize testcase "test01"`
*   `Load design from testcase/test01/test01.v`
*   `Calculate the maximum depth from n0[0] to n3[3]`

## 錯誤排查

若系統執行異常，請檢查專案根目錄下的 **`parser_error.log`**，該檔案詳細記錄了 C++ 解析器的執行錯誤與時間戳記。

# ICCAD 2026 Problem A: LLM-Assisted Netlist Transformation

這是一個結合大型語言模型 (LLM) 與 C++ 後端引擎的電路網表 (Netlist) 處理系統。系統能夠解析 Verilog 網表、分析電路結構（如路徑計數、深度計算）並進行閘級轉換（如更換閘類型）。

## 專案架構

```text
ICCAD_A/
├── .github/                   # CI/CD 設定
│   └── workflows/             # GitHub Actions 自動化測試與編譯工作流
│
├── src/                       # 核心原始碼目錄
│   ├── agent/                 # AI 代理人核心
│   │   ├── planner.py         # 任務規劃器，協調 LLM 與 Tool 呼叫
│   │   ├── llm_client.py      # LLM API 封裝 (支援 OpenAI/Anthropic)
│   │   └── tool_spec.py       # 定義暴露給 AI 的工具介面
│   │
│   ├── eda_engine/            # EDA 引擎封裝與 C++ 核心
│   │   ├── engine.py          # Python 介面，透過子程序呼叫 C++ Parser
│   │   └── parser/            # C++ 核心解析器
│   │       ├── parser.cpp
│   │       └── parser.hpp
│   │
│   └── utils/                 # 系統通用工具
│       ├── io_manager.py      # 輸出格式 (#RESPONSE) 與 Log 記錄
│       ├── config.py          # 設定檔解析 (YAML & .env)
│       └── paths.py           # 專案根目錄等路徑常數
│
├── tests/
│   ├── unit_tests/            # 單元 / 元件測試
│   └── integration_tests/     # 整合測試（模擬 main loop）
│
├── testcase/                  # 官方測試案例（保持在外層方便掛載/讀取）
├── docs/                      # 系統架構與開發文件
├── scripts/                   # 開發輔助腳本
│   └── build_parser.py        # 跨平台編譯 C++ parser
│
├── tools/abc/                 # abc 工具（需自行 clone）
│
├── config.yaml                # 系統執行設定
├── docker-compose.yml         # 本機容器化開發環境
├── main.py                    # 系統入口點
├── requirements.txt
└── README.md
```

## 環境建置

1. **建立虛擬環境並安裝套件**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **編譯 C++ Parser**（Linux / macOS / Windows 通用）:
   ```bash
   python scripts/build_parser.py
   ```
   - Linux / macOS → `src/eda_engine/parser/parser_cpp`
   - Windows → `src/eda_engine/parser/parser_cpp.exe`
   - 可覆寫：`PARSER_BIN=/path/to/parser python main.py -config config.yaml`

3. **設定 API 金鑰** — 建立 `.env`:
   ```text
   ANTHROPIC_API_KEY=your_key_here
   OPENAI_API_KEY=your_key_here
   ```

4. **（選用）abc 工具**:
   ```bash
   cd tools && git clone https://github.com/berkeley-abc/abc.git
   cd abc && make
   ```

## 執行方式

```bash
python main.py -config config.yaml
```

## 測試

```bash
python tests/integration_tests/run_test.py
python tests/unit_tests/verify_integration.py
```

## Log 檔案位置

| 類型 | 路徑 |
|------|------|
| 對話 log | `testcase/<case_name>/<case_name>.log` |
| Parser 錯誤 | `parser_error.log`（專案根目錄） |
| 輸出 netlist | `testcase/<case_name>/<case_name>_out.v` |

## 跨平台協作

| 項目 | 做法 |
|------|------|
| Parser 二進位 | 各自 `python scripts/build_parser.py`，不要 commit |
| Python 依賴 | 各自建立 `venv` |
| API 金鑰 | 放在 `.env` |
| LLM 設定 | 本地修改 `config.yaml` |

## 文件

詳見 [`docs/`](./docs/) 目錄：

- [SDD.md](./docs/SDD.md) — 系統設計
- [TSD.md](./docs/TSD.md) — 技術規格（未實作功能）
- [IMPLEMENTATION_STATUS.md](./docs/IMPLEMENTATION_STATUS.md) — 實作進度追蹤

## 錯誤排查

若系統執行異常，請檢查專案根目錄下的 **`parser_error.log`**。

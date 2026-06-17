#!/usr/bin/env python3
import argparse
import os
import sys
import pexpect

def run_testcase(case_name: str, debug: bool = False):
    # 設定路徑 (考量此腳本位於 scripts/ 內，根目錄為上一層，或從專案根目錄執行)
    # 這裡我們假設執行時的 working directory 是專案根目錄 (包含 testcase 與 main.py)
    prompt_path = os.path.join("testcase", case_name, "prompt.txt")
    log_path = os.path.join("testcase", case_name, "test_run.log")
    
    if not os.path.isfile(prompt_path):
        print(f"[!] Error: {prompt_path} not found. Skipping {case_name}.")
        return False
        
    # 讀取非空白的對話輪次
    with open(prompt_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
        
    print(f"\n[*] Running {case_name} ({len(lines)} turns)...")
    
    # 啟動 EDA 引擎
    cmd = "python3 main.py -config config.yaml"
    if debug:
        cmd += " --debug"

    try:
        # encoding="utf-8" 讓 pexpect 處理字串而非 bytes
        # timeout 設定為 300 秒 (5 分鐘) 以應付 LLM 較長的回覆時間
        child = pexpect.spawn(cmd, encoding="utf-8", timeout=300)
    except Exception as e:
        print(f"[!] Failed to start main.py: {e}")
        return False
        
    with open(log_path, "w", encoding="utf-8") as log_file:
        # 只記錄從終端機讀取到的內容 (因為 pty 預設會 echo 我們的輸入，這樣 prompt 就只會出現一次)
        child.logfile_read = log_file 
        
        # 逐行執行 prompt
        for turn, prompt in enumerate(lines, start=1):
            display_prompt = prompt if len(prompt) < 60 else prompt[:57] + "..."
            print(f"  -> [Turn {turn}] Sending: {display_prompt}")
            
            child.sendline(prompt)
            
            end_marker = f"#END {turn}"
            try:
                child.expect_exact(end_marker)
                print(f"  <- [Turn {turn}] Received: {end_marker}")
            except pexpect.TIMEOUT:
                print(f"[!] Timeout waiting for '{end_marker}' in {case_name}.")
                child.terminate(force=True)
                return False
            except pexpect.EOF:
                print(f"[!] Unexpected EOF while waiting for '{end_marker}' in {case_name}.")
                return False
                
        # 執行完畢後直接送出 EOF 關閉程序 (模擬 Ctrl+D)
        try:
            child.sendeof()
            child.expect(pexpect.EOF, timeout=2)
        except Exception:
            pass
        child.terminate(force=True)
            
    print(f"[+] Successfully finished {case_name}.")
    return True

def main():
    parser = argparse.ArgumentParser(description="EDA System Automated Test Runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case", type=str, help="Run a single test case (e.g., test02)")
    group.add_argument("--range", type=str, help="Run a range of test cases (e.g., test01-test10)")
    group.add_argument("--all", action="store_true", help="Run all test cases (test01 to test40")
    
    parser.add_argument("--debug", action="store_true", help="Enable debug mode in the engine and log to test_run.log")

    args = parser.parse_args()
    cases_to_run = []
    
    if args.case:
        cases_to_run.append(args.case)
    elif args.range:
        parts = args.range.split("-")
        if len(parts) != 2:
            print("[!] Error: Invalid range format. Use format like 'test01-test10'")
            sys.exit(1)
            
        start_case, end_case = parts[0], parts[1]
        try:
            start_num = int(start_case.replace("test", ""))
            end_num = int(end_case.replace("test", ""))
        except ValueError:
            print("[!] Error: Test cases must end with numbers (e.g., test01)")
            sys.exit(1)
            
        for i in range(start_num, end_num + 1):
            cases_to_run.append(f"test{i:02d}")
            
    elif args.all:
        for i in range(1, 41):
            cases_to_run.append(f"test{i:02d}")
            
    print(f"[*] Planning to run {len(cases_to_run)} test case(s)...")
    
    success_count = 0
    for case in cases_to_run:
        if run_testcase(case, debug=args.debug):
            success_count += 1
            
    print(f"\n[*] Testing finished. {success_count}/{len(cases_to_run)} cases completed successfully.")

if __name__ == "__main__":
    main()

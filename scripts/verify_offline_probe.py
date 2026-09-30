"""
Offline Probe Verification Script:
Allows user to test AGY CLI execution after quitting the Antigravity App.

Usage:
1. Run this script in standard macOS Terminal.app:
   python3 scripts/verify_offline_probe.py
2. The script schedules a launchd job to execute 15 seconds in the future.
3. Quit Antigravity App completely (Cmd+Q).
4. Wait 30 seconds, then check /tmp/agy_offline_probe_result.json.
"""

import json
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main():
    print("==================================================")
    print("AGY 离线/闭门后台执行能力独立验证程序")
    print("==================================================")

    token = f"TOKEN_OFFLINE_{secrets.token_hex(8)}"
    probe_dir = Path("/tmp") / f"agy_offline_probe_{secrets.token_hex(4)}"
    if probe_dir.exists():
        shutil.rmtree(probe_dir)
    probe_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=str(probe_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "offline@example.com"], cwd=str(probe_dir), check=True)
    subprocess.run(["git", "config", "user.name", "Offline Probe"], cwd=str(probe_dir), check=True)

    result_json = Path("/tmp/agy_offline_probe_result.json")
    if result_json.exists():
        result_json.unlink()

    prompt = (
        f"只在当前目录创建 probe-result.txt，文件内容严格且仅写入单行：PROBE_RESULT={token}，"
        f"严禁修改或操作任何其他文件或父级目录。"
    )

    agy_bin = "/Users/yoyotaozhou/.local/bin/agy"
    model = "gemini-3.8-flash-high"

    # Write execution shell script
    runner_sh = probe_dir / "run_probe.sh"
    runner_sh.write_text(
        f"""#!/bin/bash
sleep 15
export PATH="/Users/yoyotaozhou/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "{probe_dir}"
START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
"{agy_bin}" --print "{prompt}" --model {model} --dangerously-skip-permissions > "{probe_dir}/stdout.log" 2> "{probe_dir}/stderr.log"
EXIT_CODE=$?
END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

TARGET_FILE="{probe_dir}/probe-result.txt"
EXISTS=false
CONTENT=""
if [ -f "$TARGET_FILE" ]; then
    EXISTS=true
    CONTENT=$(cat "$TARGET_FILE")
fi

PASSED=false
if [ $EXIT_CODE -eq 0 ] && [ "$EXISTS" = true ] && [[ "$CONTENT" == *"{token}"* ]]; then
    PASSED=true
fi

cat <<EOF > "{result_json}"
{{
  "step": "app_closed_offline_probe",
  "passed": $PASSED,
  "token": "{token}",
  "probe_dir": "{probe_dir}",
  "exit_code": $EXIT_CODE,
  "start_time": "$START_TIME",
  "end_time": "$END_TIME",
  "target_file_exists": $EXISTS,
  "actual_content": "$CONTENT"
}}
EOF
""",
        encoding="utf-8",
    )
    runner_sh.chmod(0o755)

    service_label = "com.vmv.probe_offline"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{service_label}.plist"
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{service_label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{runner_sh}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/{service_label}.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/{service_label}.log</string>
</dict>
</plist>
"""
    plist_path.write_text(plist_content, encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    res = subprocess.run(["launchctl", "load", "-w", str(plist_path)], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[-] 加载 launchd 服务失败: {res.stderr}")
        return 1

    print("[+] 离线验证服务已通过 launchd 成功排期！")
    print(f"[+] 随机令牌: {token}")
    print("[+] 请在 15 秒内完全退出 Antigravity / 宿主 IDE (Cmd + Q)！")
    print("[+] 等待 45 秒后，在终端中查看执行结果：")
    print(f"    cat {result_json}")
    print("==================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())

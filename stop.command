#!/bin/bash
cd "$(dirname "$0")"

APP_NAME="SilentBackup"
PID=$(pgrep -f "python3.*main.py" | head -1)

if [ -z "$PID" ]; then
    echo "程序未运行"
    exit 1
fi

kill "$PID"
echo "已停止 SilentBackup (PID: $PID)"
#!/bin/bash
cd "$(dirname "$0")"

PID=$(pgrep -f "[p]ython.*main.py" | head -1)

if [ -z "$PID" ]; then
    echo "程序未运行"
    exit 0
fi

kill "$PID" 2>/dev/null
sleep 1

if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null
    echo "已强制停止 SilentBackup (PID: $PID)"
else
    echo "已停止 SilentBackup (PID: $PID)"
fi

#!/bin/bash
cd "$(dirname "$0")"

for py in python3 python; do
    if command -v "$py" &>/dev/null; then
        exec "$py" main.py
    fi
done

echo "错误: 未找到 Python，请先安装 Python 3" >&2
exit 1

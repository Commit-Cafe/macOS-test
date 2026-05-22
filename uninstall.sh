#!/bin/bash
set -e

PLIST_NAME="com.filewatcher.mac"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "正在卸载 FileWatcherMac..."

if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm "$PLIST_PATH"
    echo "已删除 launchd 服务: $PLIST_PATH"
else
    echo "未找到 launchd 服务文件"
fi

echo ""
echo "如需删除配置文件:"
echo "  rm -rf ~/Library/Application\\ Support/FileWatcherMac"
echo "  rm -rf ~/Library/Logs/FileWatcherMac"
echo ""
echo "卸载完成。"

#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.filewatcher.mac"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_DIR="$HOME/Library/Logs/FileWatcherMac"
LOG_FILE="$LOG_DIR/app.log"
PYTHON3_PATH="$(which python3)"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  FileWatcherMac 安装脚本${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

echo -e "${YELLOW}[1/5] 检查 Python3...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1)
    echo "  找到: $PYTHON_VERSION ($PYTHON3_PATH)"
else
    echo -e "${RED}  错误: 未找到 python3，请先安装 Python3${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}[2/5] 安装 Python 依赖...${NC}"
python3 -m pip install --user -r "${SCRIPT_DIR}/requirements.txt"
echo "  依赖安装完成"

echo ""
echo -e "${YELLOW}[3/5] 创建必要目录...${NC}"
mkdir -p "$LOG_DIR"
echo "  日志目录: $LOG_DIR"

echo ""
echo -e "${YELLOW}[4/5] 配置 launchd 开机自启服务...${NC}"
cat > "$PLIST_PATH" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON3_PATH}</string>
        <string>${SCRIPT_DIR}/app.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_FILE}</string>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST_EOF

echo "  plist 已生成: $PLIST_PATH"

echo ""
echo -e "${YELLOW}[5/5] 加载 launchd 服务...${NC}"
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "  服务已加载"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  安装完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  应用将自动启动。也可以手动运行:"
echo "    python3 ${SCRIPT_DIR}/app.py"
echo ""
echo "  日志文件: $LOG_FILE"
echo ""
echo "  管理服务命令:"
echo "    启动: launchctl load \$PLIST_PATH"
echo "    停止: launchctl unload \$PLIST_PATH"
echo "    查看状态: launchctl list | grep filewatcher"
echo ""

echo -e "${YELLOW}正在启动应用...${NC}"
python3 "${SCRIPT_DIR}/app.py" &
echo -e "${GREEN}应用已启动！请查看菜单栏的 📁 图标。${NC}"

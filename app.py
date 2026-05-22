import logging
import os
import subprocess

import rumps

from config import load_config, save_config, update_config
from file_watcher import WatcherService

APP_NAME = "📁 FileWatcher"
LOG_FILE = os.path.expanduser("~/Library/Logs/FileWatcherMac/app.log")

rumps.debug_mode(True)

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("app")


class FileWatcherApp(rumps.App):
    def __init__(self):
        super(FileWatcherApp, self).__init__(
            APP_NAME,
            title=None,
            icon=None,
            quit_button=None,
        )
        self.config = load_config()
        self.watcher = WatcherService()
        self._copy_count = 0

        self._build_menu()

        if self.config.get("source_dir") and self.config.get("dest_dir"):
            if self.config.get("monitoring"):
                self._start_watching()

    def _build_menu(self):
        self.menu = [
            self._source_menu_item(),
            self._dest_menu_item(),
            None,
            self._status_item(),
            self._toggle_menu_item(),
            None,
            self._count_item(),
            self._open_log_item(),
            None,
            self._auto_start_item(),
            self._install_launchd_item(),
            None,
            rumps.MenuItem("退出", callback=self._on_quit),
        ]

    def _source_menu_item(self):
        src = self.config.get("source_dir", "")
        label = f"📂 目标文件夹: {self._short_path(src)}" if src else "📂 选择目标文件夹..."
        return rumps.MenuItem(label, callback=self._on_select_source)

    def _dest_menu_item(self):
        dst = self.config.get("dest_dir", "")
        label = f"📁 复制文件夹: {self._short_path(dst)}" if dst else "📁 选择复制文件夹..."
        return rumps.MenuItem(label, callback=self._on_select_dest)

    def _status_item(self):
        if self.watcher.is_watching:
            return rumps.MenuItem("● 监控运行中", callback=None)
        return rumps.MenuItem("○ 监控未启动", callback=None)

    def _toggle_menu_item(self):
        if self.watcher.is_watching:
            return rumps.MenuItem("⏹ 停止监控", callback=self._on_stop)
        return rumps.MenuItem("▶ 开始监控", callback=self._on_start)

    def _count_item(self):
        return rumps.MenuItem(f"已复制: {self._copy_count} 个文件", callback=None)

    def _open_log_item(self):
        return rumps.MenuItem("📋 查看日志", callback=self._on_open_log)

    def _auto_start_item(self):
        item = rumps.MenuItem("🔄 开机自启动", callback=self._on_toggle_auto_start)
        item.state = self.config.get("auto_start", False)
        return item

    def _install_launchd_item(self):
        return rumps.MenuItem("⚙️ 安装/更新自启服务", callback=self._on_install_launchd)

    @staticmethod
    def _short_path(path, max_len=35):
        if not path:
            return ""
        home = os.path.expanduser("~")
        if path.startswith(home):
            path = "~" + path[len(home):]
        if len(path) > max_len:
            return "..." + path[-(max_len - 3):]
        return path

    def _refresh_menu_state(self):
        self.menu = [
            self._source_menu_item(),
            self._dest_menu_item(),
            None,
            self._status_item(),
            self._toggle_menu_item(),
            None,
            self._count_item(),
            self._open_log_item(),
            None,
            self._auto_start_item(),
            self._install_launchd_item(),
            None,
            rumps.MenuItem("退出", callback=self._on_quit),
        ]

    def _on_select_source(self, _):
        response = rumps.Window(
            title="选择目标文件夹（监控此文件夹的新文件）",
            message="请输入目标文件夹的完整路径：\n例如: /Users/你的用户名/Downloads",
            default_text=self.config.get("source_dir", ""),
            ok="确定",
            cancel="取消",
        ).run()
        if response.clicked:
            path = response.text.strip()
            path = os.path.expanduser(path)
            if os.path.isdir(path):
                self.config = update_config("source_dir", path)
                self._refresh_menu_state()
                rumps.notification(
                    title=APP_NAME,
                    subtitle="目标文件夹已设置",
                    message=path,
                )
            else:
                rumps.alert(
                    title="路径无效",
                    message=f"目录不存在:\n{path}",
                    ok="好的",
                )

    def _on_select_dest(self, _):
        response = rumps.Window(
            title="选择复制存放文件夹",
            message="请输入复制存放文件夹的完整路径：\n例如: /Users/你的用户名/Backup",
            default_text=self.config.get("dest_dir", ""),
            ok="确定",
            cancel="取消",
        ).run()
        if response.clicked:
            path = response.text.strip()
            path = os.path.expanduser(path)
            os.makedirs(path, exist_ok=True)
            self.config = update_config("dest_dir", path)
            self._refresh_menu_state()
            rumps.notification(
                title=APP_NAME,
                subtitle="复制文件夹已设置",
                message=path,
            )

    def _on_start(self, _):
        src = self.config.get("source_dir", "")
        dst = self.config.get("dest_dir", "")

        if not src:
            rumps.alert(title="无法启动", message="请先设置目标文件夹", ok="好的")
            return
        if not dst:
            rumps.alert(title="无法启动", message="请先设置复制存放文件夹", ok="好的")
            return
        if not os.path.isdir(src):
            rumps.alert(title="无法启动", message=f"目标文件夹不存在:\n{src}", ok="好的")
            return

        self._start_watching()

    def _start_watching(self):
        src = self.config.get("source_dir", "")
        dst = self.config.get("dest_dir", "")
        recursive = self.config.get("recursive", True)

        try:
            self.watcher.start(
                src, dst, recursive=recursive, callback=self._on_file_copied
            )
            self.config = update_config("monitoring", True)
            self._refresh_menu_state()
            rumps.notification(
                title=APP_NAME,
                subtitle="监控已启动",
                message=f"监控: {self._short_path(src)}",
            )
        except Exception as e:
            logger.error("Failed to start watcher: %s", e)
            rumps.alert(title="启动失败", message=str(e), ok="好的")

    def _on_file_copied(self, src_path):
        self._copy_count += 1
        filename = os.path.basename(src_path)
        rumps.notification(
            title=APP_NAME,
            subtitle="文件已复制",
            message=filename,
        )

    def _on_stop(self, _):
        self.watcher.stop()
        self.config = update_config("monitoring", False)
        self._refresh_menu_state()
        rumps.notification(title=APP_NAME, subtitle="监控已停止", message="")

    def _on_open_log(self, _):
        subprocess.Popen(["open", LOG_FILE])

    def _on_toggle_auto_start(self, sender):
        new_state = not sender.state
        sender.state = new_state
        self.config = update_config("auto_start", new_state)
        if new_state:
            self._install_launchd_plist()
            rumps.notification(
                title=APP_NAME, subtitle="开机自启已开启", message="已安装 launchd 服务"
            )
        else:
            self._uninstall_launchd_plist()
            rumps.notification(
                title=APP_NAME, subtitle="开机自启已关闭", message="已卸载 launchd 服务"
            )

    def _on_install_launchd(self, _):
        self._install_launchd_plist()
        self.config = update_config("auto_start", True)
        self._refresh_menu_state()
        rumps.alert(
            title="安装完成",
            message="开机自启服务已安装。\n下次登录时将自动启动。",
            ok="好的",
        )

    def _get_launchd_plist_path(self):
        return os.path.expanduser(
            "~/Library/LaunchAgents/com.filewatcher.mac.plist"
        )

    def _get_python_path(self):
        return subprocess.check_output(["which", "python3"]).decode().strip()

    def _get_app_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def _install_launchd_plist(self):
        python_path = self._get_python_path()
        app_dir = self._get_app_dir()
        plist_path = self._get_launchd_plist_path()
        log_path = LOG_FILE

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.filewatcher.mac</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{os.path.join(app_dir, "app.py")}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>WorkingDirectory</key>
    <string>{app_dir}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>"""

        os.makedirs(os.path.dirname(plist_path), exist_ok=True)
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(plist_content)

        subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
        subprocess.run(["launchctl", "load", plist_path], capture_output=True)
        logger.info("launchd plist installed: %s", plist_path)

    def _uninstall_launchd_plist(self):
        plist_path = self._get_launchd_plist_path()
        if os.path.exists(plist_path):
            subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
            os.remove(plist_path)
            logger.info("launchd plist removed: %s", plist_path)

    def _on_quit(self, _):
        if self.watcher.is_watching:
            self.watcher.stop()
            self.config = update_config("monitoring", False)
        rumps.quit_application()


if __name__ == "__main__":
    app = FileWatcherApp()
    app.run()

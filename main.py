# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import shutil
import hashlib
import logging
import subprocess
import threading
from logging.handlers import RotatingFileHandler
from datetime import datetime

import rumps
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


def _get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _get_data_dir():
    d = os.path.join(os.path.expanduser("~"), "Library", "Logs", "SilentBackup")
    os.makedirs(d, exist_ok=True)
    return d


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(
            os.path.join(_get_data_dir(), "backup.log"), encoding="utf-8",
            maxBytes=5 * 1024 * 1024, backupCount=3
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SilentBackup")


def load_config():
    if getattr(sys, "frozen", False):
        config_path = os.path.join(sys._MEIPASS, "config.json")
    else:
        config_path = os.path.join(_get_app_dir(), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    config.setdefault("backup_root", os.path.join(os.path.expanduser("~"), ".silent_backup_data"))
    config.setdefault("watch_dirs", {"desktop": True, "downloads": True, "wechat": True})
    config.setdefault("usb_monitor", True)
    config.setdefault("copy_delay_seconds", 2)
    config.setdefault("max_file_size_mb", 500)
    config.setdefault("file_extensions", {"include": [], "exclude": []})
    return config


def get_file_hash(filepath):
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
    except (PermissionError, OSError):
        return None
    return h.hexdigest()


def get_backup_dir(config, source_type):
    date_str = datetime.now().strftime("%Y-%m-%d")
    backup_dir = os.path.join(config["backup_root"], date_str, source_type)
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def hide_file(filepath):
    try:
        subprocess.run(["chflags", "hidden", filepath], check=False, capture_output=True)
    except Exception:
        pass


def hide_directory(dirpath):
    try:
        subprocess.run(["chflags", "hidden", dirpath], check=False, capture_output=True)
    except Exception:
        pass


def should_backup_file(filepath, config):
    ext = os.path.splitext(filepath)[1].lower()
    include_exts = config.get("file_extensions", {}).get("include", [])
    if include_exts and ext not in include_exts:
        return False
    exclude_list = config.get("file_extensions", {}).get("exclude", [])
    if ext in exclude_list:
        return False
    max_size = config.get("max_file_size_mb", 500) * 1024 * 1024
    try:
        if os.path.getsize(filepath) > max_size:
            return False
    except (PermissionError, OSError):
        return False
    return True


def silent_copy(src_path, config, source_type):
    try:
        if not os.path.isfile(src_path):
            return False
        if not should_backup_file(src_path, config):
            return False

        backup_dir = get_backup_dir(config, source_type)
        filename = os.path.basename(src_path)
        dst_path = os.path.join(backup_dir, filename)

        if os.path.exists(dst_path):
            src_hash = get_file_hash(src_path)
            dst_hash = get_file_hash(dst_path)
            if src_hash and src_hash == dst_hash:
                return False

        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dst_path):
            dst_path = os.path.join(backup_dir, f"{base}_{counter}{ext}")
            counter += 1

        shutil.copy2(src_path, dst_path)
        hide_file(dst_path)

        logger.info(f"[{source_type}] 已备份: {src_path} -> {dst_path}")
        return True
    except Exception as e:
        logger.error(f"[{source_type}] 备份失败 {src_path}: {e}")
        return False


class BackupEventHandler(FileSystemEventHandler):
    def __init__(self, config, source_type):
        super().__init__()
        self.config = config
        self.source_type = source_type
        self._recent_files = {}
        self._lock = threading.Lock()
        self._last_cleanup = 0.0

    def _cleanup_recent(self, now):
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        stale = [k for k, v in self._recent_files.items() if now - v > 120]
        for k in stale:
            del self._recent_files[k]

    def _handle_file(self, event):
        if event.is_directory:
            return
        src_path = event.src_path
        delay = self.config.get("copy_delay_seconds", 2)
        now = time.time()

        with self._lock:
            self._cleanup_recent(now)
            if src_path in self._recent_files:
                if now - self._recent_files[src_path] < delay:
                    return
            self._recent_files[src_path] = now

        if not os.path.exists(src_path):
            return

        time.sleep(delay)
        if os.path.exists(src_path):
            silent_copy(src_path, self.config, self.source_type)

    def on_created(self, event):
        self._handle_file(event)

    def on_modified(self, event):
        self._handle_file(event)

    def on_moved(self, event):
        if event.is_directory:
            return
        self._handle_file(event)
        if os.path.exists(event.dest_path):
            silent_copy(event.dest_path, self.config, self.source_type)


class USBDetector:
    def __init__(self, config, callback):
        self.config = config
        self.callback = callback
        self._running = False
        self._thread = None
        self._known_volumes = set()
        self._scanned_files = set()
        self._scan_lock = threading.Lock()

    def _get_removable_volumes(self):
        volumes = set()
        try:
            result = subprocess.run(
                ["ls", "-1", "/Volumes/"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    vol_name = line.strip()
                    if vol_name and vol_name != "Macintosh HD":
                        vol_path = os.path.join("/Volumes", vol_name)
                        if os.path.ismount(vol_path):
                            volumes.add(vol_path)
        except Exception as e:
            logger.error(f"[USB] 获取卷列表失败: {e}")
        return volumes

    def _scan_volume(self, volume_path):
        logger.info(f"[USB] 扫描外接磁盘: {volume_path}")
        count = 0
        try:
            for root, dirs, files in os.walk(volume_path):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fname in files:
                    if fname.startswith("."):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        file_key = f"{fpath}_{os.path.getmtime(fpath)}"
                    except OSError:
                        continue
                    with self._scan_lock:
                        if file_key in self._scanned_files:
                            continue
                        self._scanned_files.add(file_key)
                    if silent_copy(fpath, self.config, "usb"):
                        count += 1
        except PermissionError:
            logger.warning(f"[USB] 权限不足，跳过部分目录: {volume_path}")
        logger.info(f"[USB] 外接磁盘 {volume_path} 扫描完成, 备份了 {count} 个文件")

    def _monitor(self):
        self._known_volumes = self._get_removable_volumes()
        logger.info(f"[USB] 初始检测到外接磁盘: {self._known_volumes}")

        while self._running:
            try:
                current_volumes = self._get_removable_volumes()
                new_volumes = current_volumes - self._known_volumes
                for vol in new_volumes:
                    logger.info(f"[USB] 检测到新外接磁盘: {vol}")
                    time.sleep(3)
                    self._scan_volume(vol)
                removed = self._known_volumes - current_volumes
                if removed:
                    logger.info(f"[USB] 磁盘已移除: {removed}")
                self._known_volumes = current_volumes
            except Exception as e:
                logger.error(f"[USB] 监控出错: {e}")
            time.sleep(2)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()
        logger.info("[USB] 外接磁盘监控已启动")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[USB] 外接磁盘监控已停止")


class WeChatPathFinder:
    @staticmethod
    def find_wechat_paths():
        home = os.path.expanduser("~")
        mac_paths = [
            os.path.join(home, "Library", "Containers", "com.tencent.xinWeChat",
                         "Data", "Library", "Application Support", "com.tencent.xinWeChat"),
            os.path.join(home, "Library", "Containers", "com.tencent.xinWeChat",
                         "Data", "Documents"),
        ]
        return [p for p in mac_paths if os.path.exists(p)]


class BackupEngine:
    def __init__(self):
        self.config = load_config()
        self.observer = None
        self.usb_detector = None
        self._running = False
        self._stats = {"wechat": 0, "usb": 0, "desktop": 0, "downloads": 0}

    def _get_watch_paths(self):
        paths = []
        home = os.path.expanduser("~")

        if self.config["watch_dirs"].get("desktop", True):
            desktop = os.path.join(home, "Desktop")
            if os.path.exists(desktop):
                paths.append(("desktop", desktop))

        if self.config["watch_dirs"].get("downloads", True):
            downloads = os.path.join(home, "Downloads")
            if os.path.exists(downloads):
                paths.append(("downloads", downloads))

        if self.config["watch_dirs"].get("wechat", True):
            wechat_paths = WeChatPathFinder.find_wechat_paths()
            for p in wechat_paths:
                paths.append(("wechat", p))

        return paths

    def get_status(self):
        try:
            backup_dir = self.config["backup_root"]
            date_str = datetime.now().strftime("%Y-%m-%d")
            today_dir = os.path.join(backup_dir, date_str)
            count = 0
            details = []
            if os.path.exists(today_dir):
                for source_type in ["wechat", "usb", "desktop", "downloads"]:
                    type_dir = os.path.join(today_dir, source_type)
                    if os.path.exists(type_dir):
                        type_count = 0
                        for _, _, files in os.walk(type_dir):
                            type_count += len(files)
                        count += type_count
                        details.append(f"{source_type}: {type_count}")
            return count, details
        except Exception:
            return 0, []

    def start(self):
        if self._running:
            return
        self._running = True

        os.makedirs(self.config["backup_root"], exist_ok=True)
        hide_directory(self.config["backup_root"])

        self.observer = Observer()
        watch_paths = self._get_watch_paths()

        for source_type, path in watch_paths:
            try:
                handler = BackupEventHandler(self.config, source_type)
                self.observer.schedule(handler, path, recursive=True)
                logger.info(f"[监控] 已添加: {path} ({source_type})")
            except Exception as e:
                logger.error(f"[监控] 添加失败 {path}: {e}")

        self.observer.start()

        if self.config.get("usb_monitor", True):
            self.usb_detector = USBDetector(self.config, self._on_usb_file)
            self.usb_detector.start()

        logger.info("[引擎] 备份引擎已启动")

    def _on_usb_file(self, filepath):
        self._stats["usb"] += 1

    def stop(self):
        if not self._running:
            return
        self._running = False

        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)

        if self.usb_detector:
            self.usb_detector.stop()

        logger.info("[引擎] 备份引擎已停止")


class BackupApp(rumps.App):
    def __init__(self):
        self.engine = BackupEngine()
        self._running = False
        super().__init__("🔧", template=True)

        self._status_item = rumps.MenuItem("状态: 已停止", key="status")
        self._count_item = rumps.MenuItem("今日备份: 0 个文件", key="count")

        sep = rumps.separator

        self.menu = [
            rumps.MenuItem("启动备份", callback=self._start),
            rumps.MenuItem("停止备份", callback=self._stop),
            sep,
            self._status_item,
            self._count_item,
            sep,
            rumps.MenuItem("退出", callback=self._quit),
        ]

        self._update_timer = rumps.Timer(self._update_status, 5)
        self._update_timer.start()

        logger.info("[应用] SilentBackup 菜单栏应用已启动")
        self._start(None)

    def _start(self, sender):
        try:
            self.engine.start()
            self._running = True
            self._status_item.title = "状态: 运行中"
            logger.info("[应用] 用户点击启动")
        except Exception as e:
            logger.error(f"[应用] 启动失败: {e}")

    def _stop(self, sender):
        try:
            self.engine.stop()
            self._running = False
            self._status_item.title = "状态: 已停止"
            self._count_item.title = "今日备份: 0 个文件"
            logger.info("[应用] 用户点击停止")
        except Exception as e:
            logger.error(f"[应用] 停止失败: {e}")

    def _update_status(self, sender):
        if self._running:
            count, _details = self.engine.get_status()
            self._count_item.title = f"今日备份: {count} 个文件"

    def _quit(self, sender):
        if self.engine._running:
            self.engine.stop()
        logger.info("[应用] 用户退出应用")
        rumps.quit_application()


if __name__ == "__main__":
    app = BackupApp()
    app.run()

import os
import sys
import json
import time
import shutil
import hashlib
import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import tkinter as tk
from tkinter import ttk, messagebox


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SilentBackup")


def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_file_hash(filepath):
    h = hashlib.md5()
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

    def _handle_file(self, event):
        if event.is_directory:
            return
        src_path = event.src_path
        delay = self.config.get("copy_delay_seconds", 2)

        with self._lock:
            if src_path in self._recent_files:
                if time.time() - self._recent_files[src_path] < delay:
                    return
            self._recent_files[src_path] = time.time()

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
        if not event.is_directory:
            self._handle_file(event)


class USBDetector:
    def __init__(self, config, callback):
        self.config = config
        self.callback = callback
        self._running = False
        self._thread = None
        self._known_volumes = set()
        self._scanned_files = set()

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

    def _is_removable(self, mount_point):
        try:
            result = subprocess.run(
                ["diskutil", "info", mount_point],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout.lower()
            if "removable" in output or "external" in output:
                return True
            if "type: virtual" in output:
                return False
            return False
        except Exception:
            return False

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
                    if file_key not in self._scanned_files:
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
        paths = []
        home = os.path.expanduser("~")

        mac_paths = [
            os.path.join(home, "Library", "Containers", "com.tencent.xinWeChat",
                         "Data", "Library", "Application Support", "com.tencent.xinWeChat"),
            os.path.join(home, "Library", "Containers", "com.tencent.xinWeChat",
                         "Data", "Documents"),
        ]

        for base in mac_paths:
            if not os.path.exists(base):
                continue
            for root, dirs, files in os.walk(base):
                depth = root.replace(base, "").count(os.sep)
                if depth > 5:
                    dirs[:] = []
                    continue
                for d in dirs:
                    if d.startswith("."):
                        continue
                if "FileStorage" in root or "Message" in root or "Attachment" in root:
                    paths.append(root)
                if root.endswith("File") or root.endswith("Files"):
                    if base not in paths:
                        paths.append(root)

        seen = set()
        unique = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique


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

    def start(self, status_callback=None):
        if self._running:
            return
        self._running = True
        self._status_callback = status_callback

        os.makedirs(self.config["backup_root"], exist_ok=True)
        hide_directory(self.config["backup_root"])

        self.observer = Observer()
        watch_paths = self._get_watch_paths()

        for source_type, path in watch_paths:
            try:
                handler = BackupEventHandler(self.config, source_type)
                self.observer.schedule(handler, path, recursive=True)
                logger.info(f"[监控] 已添加: {path} ({source_type})")
                if status_callback:
                    status_callback(f"监控: {path}")
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


class BackupApp:
    def __init__(self):
        self.engine = BackupEngine()
        self.root = tk.Tk()
        self.root.title("系统维护工具")
        self.root.geometry("420x300")
        self.root.resizable(False, False)

        self.root.configure(bg="#2b2b2b")

        self._build_ui()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._running = False

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background="#2b2b2b")
        style.configure("TLabel", background="#2b2b2b", foreground="#cccccc",
                         font=("PingFang SC", 12))
        style.configure("Title.TLabel", background="#2b2b2b", foreground="#ffffff",
                         font=("PingFang SC", 16, "bold"))
        style.configure("Status.TLabel", background="#2b2b2b", foreground="#88cc88",
                         font=("PingFang SC", 11))
        style.configure("Green.TButton", font=("PingFang SC", 12))
        style.configure("Red.TButton", font=("PingFang SC", 12))

        frame = ttk.Frame(self.root, style="TFrame", padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="系统维护工具", style="Title.TLabel").pack(pady=(0, 15))

        self.status_label = ttk.Label(frame, text="状态: 未启动", style="Status.TLabel")
        self.status_label.pack(pady=5)

        self.detail_label = ttk.Label(frame, text="", style="TLabel", wraplength=360)
        self.detail_label.pack(pady=5)

        btn_frame = ttk.Frame(frame, style="TFrame")
        btn_frame.pack(pady=15)

        self.start_btn = ttk.Button(btn_frame, text="▶ 启动", command=self._start,
                                     width=15, style="Green.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=10)

        self.stop_btn = ttk.Button(btn_frame, text="■ 停止", command=self._stop,
                                    width=15, style="Red.TButton", state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=10)

        self.info_label = ttk.Label(frame, text="启动后将自动运行维护任务", style="TLabel")
        self.info_label.pack(pady=10)

        self.count_label = ttk.Label(frame, text="", style="TLabel")
        self.count_label.pack(pady=5)

    def _update_status(self, msg):
        self.detail_label.config(text=msg)

    def _start(self):
        try:
            self.engine.start(status_callback=self._update_status)
            self._running = True
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.status_label.config(text="状态: 运行中 ✓", foreground="#88cc88")
            self.info_label.config(text="维护任务正在后台运行...")
            self._update_log_count()
        except Exception as e:
            messagebox.showerror("错误", f"启动失败: {e}")

    def _stop(self):
        try:
            self.engine.stop()
            self._running = False
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.status_label.config(text="状态: 已停止", foreground="#cc8888")
            self.info_label.config(text="维护任务已停止")
        except Exception as e:
            messagebox.showerror("错误", f"停止失败: {e}")

    def _update_log_count(self):
        if not self._running:
            return
        try:
            backup_dir = self.engine.config["backup_root"]
            date_str = datetime.now().strftime("%Y-%m-%d")
            today_dir = os.path.join(backup_dir, date_str)
            count = 0
            if os.path.exists(today_dir):
                for root, dirs, files in os.walk(today_dir):
                    count += len(files)
            self.count_label.config(text=f"今日已备份: {count} 个文件")
        except Exception:
            pass
        self.root.after(3000, self._update_log_count)

    def _on_close(self):
        if self._running:
            self.engine.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = BackupApp()
    app.run()

import hashlib
import logging
import os
import shutil
import time
import threading

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger("file_watcher")

_recently_copied = {}
_recently_copied_lock = threading.Lock()

COPY_COOLDOWN = 2.0


def _file_stable(path, wait=1.0, max_wait=10.0):
    """Wait until file size is stable (no longer being written)."""
    elapsed = 0.0
    last_size = -1
    while elapsed < max_wait:
        try:
            current_size = os.path.getsize(path)
        except OSError:
            return False
        if current_size == last_size and current_size >= 0:
            return True
        last_size = current_size
        time.sleep(wait)
        elapsed += wait
    return True


def _file_hash(path):
    """MD5 hash of file for dedup check."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _is_recently_copied(path):
    key = os.path.normpath(path)
    with _recently_copied_lock:
        if key in _recently_copied:
            if time.time() - _recently_copied[key] < COPY_COOLDOWN:
                return True
            del _recently_copied[key]
    return False


def _mark_copied(path):
    key = os.path.normpath(path)
    with _recently_copied_lock:
        _recently_copied[key] = time.time()


def copy_file(src_path, dest_dir, source_dir):
    """Copy a file preserving relative directory structure."""
    if _is_recently_copied(src_path):
        return False

    if not os.path.isfile(src_path):
        return False

    try:
        rel_path = os.path.relpath(src_path, source_dir)
    except ValueError:
        return False

    dest_path = os.path.join(dest_dir, rel_path)
    dest_parent = os.path.dirname(dest_path)

    if os.path.abspath(src_path) == os.path.abspath(dest_path):
        return False

    if os.path.exists(dest_path):
        src_hash = _file_hash(src_path)
        dst_hash = _file_hash(dest_path)
        if src_hash and dst_hash and src_hash == dst_hash:
            return False
        base, ext = os.path.splitext(dest_path)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        dest_path = f"{base}_{timestamp}{ext}"

    os.makedirs(dest_parent, exist_ok=True)

    if not _file_stable(src_path):
        logger.warning("File not stable after waiting: %s", src_path)

    try:
        shutil.copy2(src_path, dest_path)
        _mark_copied(src_path)
        logger.info("Copied: %s -> %s", src_path, dest_path)
        return True
    except OSError as e:
        logger.error("Copy failed: %s -> %s, error: %s", src_path, dest_path, e)
        return False


class CopyEventHandler(FileSystemEventHandler):
    def __init__(self, dest_dir, source_dir, callback=None):
        super().__init__()
        self.dest_dir = dest_dir
        self.source_dir = source_dir
        self.callback = callback

    def on_created(self, event):
        if event.is_directory:
            return
        src_path = event.src_path
        success = copy_file(src_path, self.dest_dir, self.source_dir)
        if success and self.callback:
            self.callback(src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        src_path = event.src_path
        success = copy_file(src_path, self.dest_dir, self.source_dir)
        if success and self.callback:
            self.callback(src_path)


class WatcherService:
    def __init__(self):
        self.observer = None
        self._watching = False

    @property
    def is_watching(self):
        return self._watching and self.observer is not None and self.observer.is_alive()

    def start(self, source_dir, dest_dir, recursive=True, callback=None):
        if self.is_watching:
            self.stop()

        if not os.path.isdir(source_dir):
            raise ValueError(f"Source directory does not exist: {source_dir}")
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)

        event_handler = CopyEventHandler(dest_dir, source_dir, callback)
        self.observer = Observer()
        self.observer.schedule(event_handler, source_dir, recursive=recursive)
        self.observer.daemon = True
        self.observer.start()
        self._watching = True
        logger.info(
            "Watching: %s -> %s (recursive=%s)", source_dir, dest_dir, recursive
        )

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)
            self.observer = None
        self._watching = False
        logger.info("Watcher stopped")

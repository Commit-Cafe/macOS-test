from setuptools import setup

APP = ["app.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "packages": ["rumps", "watchdog"],
    "includes": [
        "rumps",
        "watchdog",
        "watchdog.observers",
        "watchdog.events",
        "config",
        "file_watcher",
    ],
    "excludes": [
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "PIL",
    ],
    "iconfile": None,
    "plist": {
        "CFBundleName": "FileWatcherMac",
        "CFBundleDisplayName": "FileWatcherMac",
        "CFBundleIdentifier": "com.filewatcher.mac",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "10.13.0",
        "NSHighResolutionCapable": True,
    },
}

setup(
    name="FileWatcherMac",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)

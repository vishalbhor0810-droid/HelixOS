from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
import sys
import time
import json


# Directory names skipped anywhere below the watched folder (compared case-insensitively)
IGNORED_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".venv", "venv", "env",
    ".idea", ".vscode", ".cache", "dist", "build",
    "chroma_db", "$recycle.bin", "system volume information",
}


def is_ignored(path):
    # Only check the part below the watched root, so watching a folder that itself
    # lives under e.g. "build" still works
    try:
        rel = os.path.relpath(path, folder)
    except ValueError:  # different drive on Windows
        return False
    parts = rel.replace("\\", "/").split("/")
    return any(part.lower() in IGNORED_DIRS for part in parts)


def emit(event_type, event):
    payload = {
        "event": event_type,
        "path": event.src_path,
        "isDirectory": event.is_directory,
        "timestamp": time.time(),
    }
    if event_type == "moved":
        payload["destPath"] = event.dest_path
    print(json.dumps(payload), flush=True)


class FileHandler(FileSystemEventHandler):

    def on_created(self, event):
        if not is_ignored(event.src_path):
            emit("created", event)

    def on_deleted(self, event):
        if not is_ignored(event.src_path):
            emit("deleted", event)

    def on_modified(self, event):
        if not is_ignored(event.src_path):
            emit("modified", event)

    def on_moved(self, event):
        src_ignored = is_ignored(event.src_path)
        dest_ignored = is_ignored(event.dest_path)
        if src_ignored and dest_ignored:
            return
        if dest_ignored:
            # Moved into an ignored folder: treat as removed from the index
            emit("deleted", event)
        elif src_ignored:
            # Moved out of an ignored folder: treat as a new file at the destination
            event.src_path = event.dest_path
            emit("created", event)
        else:
            emit("moved", event)


folder = os.path.abspath(sys.argv[1])

observer = Observer()
observer.schedule(FileHandler(), folder, recursive=True)
observer.start()

print(json.dumps({"event": "watching", "path": folder, "timestamp": time.time()}), flush=True)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()

observer.join()

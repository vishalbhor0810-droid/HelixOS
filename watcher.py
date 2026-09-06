from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import sys
import time
import json


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
        emit("created", event)

    def on_deleted(self, event):
        emit("deleted", event)

    def on_modified(self, event):
        emit("modified", event)

    def on_moved(self, event):
        emit("moved", event)


folder = sys.argv[1]

observer = Observer()
observer.schedule(FileHandler(), folder, recursive=False)
observer.start()

print(json.dumps({"event": "watching", "path": folder, "timestamp": time.time()}), flush=True)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()

observer.join()
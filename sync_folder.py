#!/usr/bin/env python
"""
Bring the index in sync with a folder that changed while it wasn't monitored
(files renamed, moved, added or deleted while the app was closed).

    python sync_folder.py "C:\\Users\\Vishal\\Pictures"

1. Removes chunks for indexed files that no longer exist (old names of renamed files).
2. Indexes every supported file under the folder (recursively) that isn't indexed yet.
   Files already indexed under their current path are left alone.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.core.indexer import index_file, _is_supported
from backend.core.vector_store import prune_missing_files, list_indexed_files

# Same folders watcher.py skips
IGNORED_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".venv", "venv", "env",
    ".idea", ".vscode", ".cache", "dist", "build",
    "chroma_db", "$recycle.bin", "system volume information",
}


def _key(path):
    return os.path.normcase(os.path.abspath(path))


if __name__ == "__main__":
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        print('Usage: python sync_folder.py "<folder path>"')
        sys.exit(1)

    folder = os.path.abspath(sys.argv[1])

    pruned = prune_missing_files()
    for path in pruned["files_removed"]:
        print(f"Removed stale entry: {path}")

    indexed = {_key(p) for p in list_indexed_files()}
    added, failed = 0, 0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_DIRS]
        for name in files:
            path = os.path.join(root, name)
            if not _is_supported(path) or _key(path) in indexed:
                continue
            print(f"Indexing {path} ...", flush=True)
            try:
                result = index_file(path)
                print(f"  {result.get('status')} ({result.get('chunksIndexed', 0)} chunks)")
                added += 1
            except Exception as e:
                print(f"  error: {e}")
                failed += 1

    print(f"\nDone: {len(pruned['files_removed'])} stale file(s) removed, "
          f"{added} file(s) indexed, {failed} failed.")

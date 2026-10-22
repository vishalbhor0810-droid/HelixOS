"""
Safe file operations for chat commands ("create a folder Major and move these files into it").
Everything is confined to the workspace root (the folder selected in the UI).
"""
import os
import re
import shutil
import logging
from typing import List, Dict, Any, Optional, Tuple

from backend.core import vector_store

logger = logging.getLogger("helix.file_ops")

# Not offered to the LLM and never touched
SKIPPED_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".idea", ".vscode", ".cache", "chroma_db", "$recycle.bin", "system volume information",
}
MAX_LISTED_FILES = 200

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def is_inside(path: str, root: str) -> bool:
    try:
        path_real = os.path.normcase(os.path.realpath(path))
        root_real = os.path.normcase(os.path.realpath(root))
        return os.path.commonpath([path_real, root_real]) == root_real
    except ValueError:  # different drives on Windows
        return False


def validate_folder_name(name: str) -> Optional[str]:
    """Return an error message if name can't be used as a single folder name, else None."""
    if not name or not name.strip():
        return "Folder name is empty."
    name = name.strip()
    if name in (".", ".."):
        return f"'{name}' is not a valid folder name."
    if _INVALID_NAME_CHARS.search(name):
        return f"Folder name '{name}' contains characters Windows doesn't allow (< > : \" / \\ | ? *)."
    if name.endswith((".", " ")):
        return f"Folder name '{name}' can't end with a dot or space."
    if name.split(".")[0].lower() in _RESERVED_NAMES:
        return f"'{name}' is a reserved name on Windows."
    if len(name) > 100:
        return "Folder name is too long (max 100 characters)."
    return None


def list_workspace_files(root: str) -> Tuple[List[str], bool]:
    """Relative paths of files under root (skipping heavy/hidden dirs). Returns (paths, truncated)."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d.lower() not in SKIPPED_DIRS and not d.startswith(".")
        )
        for name in sorted(filenames):
            if name.startswith("~$"):  # Office lock files
                continue
            files.append(os.path.relpath(os.path.join(dirpath, name), root))
            if len(files) >= MAX_LISTED_FILES:
                return files, True
    return files, False


def resolve_files(root: str, rel_paths: List[str]) -> Tuple[List[str], List[str]]:
    """Map relative paths chosen by the LLM to absolute paths. Returns (resolved, invalid)."""
    resolved, invalid = [], []
    for rel in rel_paths:
        full = os.path.abspath(os.path.join(root, rel))
        if is_inside(full, root) and os.path.isfile(full):
            if full not in resolved:
                resolved.append(full)
        else:
            invalid.append(rel)
    return resolved, invalid


def _unique_destination(dest_dir: str, filename: str) -> str:
    """report.pdf -> report (1).pdf if report.pdf already exists."""
    candidate = os.path.join(dest_dir, filename)
    stem, ext = os.path.splitext(filename)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dest_dir, f"{stem} ({n}){ext}")
        n += 1
    return candidate


def execute_plan(root: str, folder_name: str, file_paths: List[str], mode: str, sync_index: bool) -> Dict[str, Any]:
    """
    Create root/folder_name and move or copy file_paths into it.
    Re-validates everything: the plan comes back from the client and must not be trusted.
    """
    if not root or not os.path.isdir(root):
        return {"status": "error", "error": "The selected workspace folder no longer exists.", "results": []}
    if mode not in ("move", "copy"):
        return {"status": "error", "error": f"Unknown mode '{mode}'.", "results": []}
    name_error = validate_folder_name(folder_name)
    if name_error:
        return {"status": "error", "error": name_error, "results": []}

    dest_dir = os.path.join(os.path.abspath(root), folder_name.strip())
    if os.path.exists(dest_dir) and not os.path.isdir(dest_dir):
        return {"status": "error", "error": f"A file named '{folder_name}' already exists here.", "results": []}

    created_folder = not os.path.isdir(dest_dir)
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        return {"status": "error", "error": f"Could not create folder: {e}", "results": []}

    results = []
    for src in file_paths:
        filename = os.path.basename(src)
        if not (is_inside(src, root) and os.path.isfile(src)):
            results.append({"file": filename, "status": "error", "error": "File not found in the workspace."})
            continue
        if os.path.normcase(os.path.dirname(os.path.abspath(src))) == os.path.normcase(dest_dir):
            results.append({"file": filename, "status": "skipped", "error": f"Already in {folder_name}."})
            continue

        dest = _unique_destination(dest_dir, filename)
        try:
            if mode == "move":
                shutil.move(src, dest)
                if sync_index:
                    # Cheap re-key of existing chunks; a no-op if the file was never indexed
                    vector_store.move_document(src, dest)
            else:
                shutil.copy2(src, dest)
            results.append({
                "file": filename,
                "status": "done",
                "dest": dest,
                "renamed": os.path.basename(dest) != filename,
            })
        except (OSError, shutil.Error) as e:
            # Typical cause: the file is open in another program
            logger.error("Failed to %s %s: %s", mode, src, e)
            results.append({"file": filename, "status": "error", "error": str(e)})

    done = sum(1 for r in results if r["status"] == "done")
    failed = sum(1 for r in results if r["status"] == "error")
    return {
        "status": "success" if not failed else ("partial" if done else "error"),
        "folder_path": dest_dir,
        "created_folder": created_folder,
        "mode": mode,
        "results": results,
    }

import os
import sys
import json
from typing import Dict, Any
from backend.core.document_processor import extract_text, EXTRACTORS
from backend.core.chunker import chunk_text
from backend.core.embedder import embed_texts
from backend.core.vector_store import replace_document, delete_by_path, move_document, move_folder


def index_file(file_path: str) -> Dict[str, Any]:
    """
    Extract text, chunk, embed, and store in vector database.
    """
    doc_result = extract_text(file_path)
    if doc_result["status"] != "success":
        return doc_result
        
    text = doc_result["text"]
    chunks = chunk_text(text)
    
    if not chunks:
        return {
            "status": "empty",
            "filename": doc_result["filename"],
            "path": doc_result["path"],
            "text": text,
            "textLength": doc_result["textLength"],
            "chunksIndexed": 0
        }
        
    chunk_texts = [c["text"] for c in chunks]
    embeddings = embed_texts(chunk_texts)
    
    indexed_count = replace_document(file_path, chunks, embeddings)
    
    return {
        "status": "success",
        "filename": doc_result["filename"],
        "path": doc_result["path"],
        "text": text,
        "textLength": doc_result["textLength"],
        "chunksIndexed": indexed_count
    }


def deindex_file(file_path: str) -> Dict[str, Any]:
    """
    Remove indexed chunks for file_path from vector database.
    """
    deleted_count = delete_by_path(file_path)
    return {
        "status": "deleted",
        "path": os.path.abspath(file_path),
        "chunksDeleted": deleted_count
    }


def _is_supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in EXTRACTORS


def move_file(src_path: str, dest_path: str) -> Dict[str, Any]:
    """
    Sync the index after a file or folder is renamed/moved.
    Re-keys existing chunks when possible; otherwise deindexes the old path
    and indexes the new one (e.g. the extension changed, or the old path was never indexed).
    """
    if os.path.isdir(dest_path):
        return {
            "status": "moved",
            "filename": os.path.basename(dest_path),
            "path": os.path.abspath(dest_path),
            "chunksMoved": move_folder(src_path, dest_path)
        }

    same_type = os.path.splitext(src_path)[1].lower() == os.path.splitext(dest_path)[1].lower()
    if same_type and _is_supported(dest_path):
        moved = move_document(src_path, dest_path)
        if moved:
            return {
                "status": "moved",
                "filename": os.path.basename(dest_path),
                "path": os.path.abspath(dest_path),
                "chunksMoved": moved
            }

    if _is_supported(src_path):
        delete_by_path(src_path)
    if _is_supported(dest_path):
        return index_file(dest_path)
    return {
        "status": "deleted",
        "filename": os.path.basename(src_path),
        "path": os.path.abspath(src_path)
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "error": "Missing file path"}))
        sys.exit(1)
        
    target_path = sys.argv[1]
    is_delete = "--delete" in sys.argv
    
    if is_delete:
        output = deindex_file(target_path)
    else:
        output = index_file(target_path)
        
    print(json.dumps(output))

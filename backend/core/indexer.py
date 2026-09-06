import os
import sys
import json
from typing import Dict, Any
from backend.core.document_processor import extract_text
from backend.core.chunker import chunk_text
from backend.core.embedder import embed_texts
from backend.core.vector_store import replace_document, delete_by_path


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

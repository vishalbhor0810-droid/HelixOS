#!/usr/bin/env python
"""
HelixOS Indexer CLI Wrapper
Delegates indexing logic to backend.core.indexer
"""
import sys
import os
import json

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.core.indexer import index_file, deindex_file

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "error": "Missing file path"}))
        sys.exit(1)
        
    target_path = sys.argv[1]
    is_delete = "--delete" in sys.argv
    
    try:
        if is_delete:
            output = deindex_file(target_path)
        else:
            output = index_file(target_path)
        print(json.dumps(output))
    except Exception as e:
        print(json.dumps({
            "status": "error",
            "path": target_path,
            "filename": os.path.basename(target_path),
            "error": str(e)
        }))
        sys.exit(1)

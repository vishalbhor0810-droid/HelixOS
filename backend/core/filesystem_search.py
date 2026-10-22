import os
import re
from typing import List, Dict, Any, Optional

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".pptx", ".png", ".jpg"}


def search_filesystem_by_name(query: str, folder_path: Optional[str] = None, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Search directory and subdirectories for files matching keywords in query.
    """
    if not folder_path or not os.path.exists(folder_path):
        return []
        
    query_tokens = [t.lower() for t in re.findall(r'\w+', query) if len(t) > 2]
    if not query_tokens:
        return []
        
    results = []
    
    for root, _, files in os.walk(folder_path):
        for file in files:
            file_lower = file.lower()
            name_no_ext, ext = os.path.splitext(file_lower)
            
            # Calculate match score based on token occurrence in filename
            matched_count = sum(1 for token in query_tokens if token in file_lower)
            if matched_count > 0:
                full_path = os.path.abspath(os.path.join(root, file))
                score = matched_count / max(len(query_tokens), 1)
                
                try:
                    stat = os.stat(full_path)
                    size = stat.st_size
                except Exception:
                    size = 0
                    
                results.append({
                    "filename": file,
                    "path": full_path,
                    "extension": ext,
                    "size": size,
                    "score": round(score, 3),
                    "matched_tokens": matched_count
                })
                
    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:max_results]


def verify_file_exists(file_path: str) -> bool:
    """Verify if a path exists and is a file."""
    if not file_path:
        return False
    return os.path.isfile(file_path)

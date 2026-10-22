import os
import hashlib
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from backend.config import settings

_client = None
_collection = None
_indexed_files: Optional[Dict[str, str]] = None  # path -> filename, rebuilt lazily after writes
_indexed_files_count = -1  # chunk count when cache was built; catches writes from other processes (index_all.py)


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
    return _client


def get_collection():
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name=settings.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
    return _collection


def _path_hash(file_path: str) -> str:
    normalized = os.path.abspath(file_path).lower().replace("\\", "/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def delete_by_path(file_path: str) -> int:
    """Delete all indexed chunks associated with a file path."""
    collection = get_collection()
    normalized_path = os.path.abspath(file_path)
    
    # Query matching documents
    existing = collection.get(where={"path": normalized_path})
    if existing and existing.get("ids"):
        ids_to_delete = existing["ids"]
        collection.delete(ids=ids_to_delete)
        _invalidate_file_cache()
        return len(ids_to_delete)
    return 0


def replace_document(file_path: str, chunks: List[Dict[str, Any]], embeddings: List[List[float]]) -> int:
    """
    Remove any existing chunks for file_path and store the new chunks and embeddings.
    """
    normalized_path = os.path.abspath(file_path)
    delete_by_path(normalized_path)
    
    if not chunks or not embeddings:
        return 0
        
    collection = get_collection()
    file_hash = _path_hash(normalized_path)
    filename = os.path.basename(normalized_path)
    ext = os.path.splitext(filename)[1].lower()

    ids = []
    documents = []
    metadatas = []
    
    for item in chunks:
        idx = item["chunk_index"]
        total = item["total_chunks"]
        text = item["text"]
        
        chunk_id = f"{file_hash}_{idx}"
        ids.append(chunk_id)
        documents.append(text)
        metadatas.append({
            "path": normalized_path,
            "filename": filename,
            "extension": ext,
            "chunk_index": idx,
            "total_chunks": total
        })
        
    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas
    )
    _invalidate_file_cache()
    return len(ids)


def move_document(old_path: str, new_path: str) -> int:
    """
    Re-key an indexed file's chunks to a new path without re-extracting or re-embedding.
    Returns the number of chunks moved (0 if old_path was not indexed).
    """
    collection = get_collection()
    old_norm = os.path.abspath(old_path)
    new_norm = os.path.abspath(new_path)

    existing = collection.get(
        where={"path": old_norm},
        include=["documents", "metadatas", "embeddings"]
    )
    old_ids = existing.get("ids") or []
    if not old_ids:
        return 0

    new_hash = _path_hash(new_norm)
    filename = os.path.basename(new_norm)
    ext = os.path.splitext(filename)[1].lower()

    new_ids = []
    new_metas = []
    for meta in existing["metadatas"]:
        new_ids.append(f"{new_hash}_{meta['chunk_index']}")
        new_metas.append({**meta, "path": new_norm, "filename": filename, "extension": ext})

    # Upsert first, then delete only the ids that changed: a case-only rename
    # (Report.pdf -> report.pdf) hashes to the same ids since _path_hash lowercases
    collection.upsert(
        ids=new_ids,
        documents=existing["documents"],
        embeddings=existing["embeddings"],
        metadatas=new_metas
    )
    new_id_set = set(new_ids)
    stale_ids = [i for i in old_ids if i not in new_id_set]
    if stale_ids:
        collection.delete(ids=stale_ids)
    _invalidate_file_cache()
    return len(new_ids)


def move_folder(old_dir: str, new_dir: str) -> int:
    """Re-key every indexed file under old_dir to the same relative path under new_dir."""
    prefix = os.path.normcase(os.path.abspath(old_dir)).rstrip("\\/") + os.sep
    new_root = os.path.abspath(new_dir)
    moved = 0
    for path in list(list_indexed_files()):
        if os.path.normcase(path).startswith(prefix):
            moved += move_document(path, os.path.join(new_root, path[len(prefix):]))
    return moved


def query(
    query_embedding: List[float],
    top_k: int = None,
    where: Optional[Dict[str, Any]] = None,
    min_relevance: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Search collection for top_k nearest chunks to query_embedding.
    """
    if top_k is None:
        top_k = settings.SIMILARITY_TOP_K
    if min_relevance is None:
        min_relevance = settings.SIMILARITY_THRESHOLD

    collection = get_collection()
    count = collection.count()
    if count == 0:
        return []
        
    k = min(top_k, count)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
        where=where,
        include=["documents", "metadatas", "distances"]
    )
    
    matches = []
    if results and results.get("documents") and len(results["documents"]) > 0:
        docs = results["documents"][0]
        metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
        distances = results["distances"][0] if results.get("distances") else [0.0] * len(docs)

        for doc, meta, dist in zip(docs, metas, distances):
            # For cosine distance, similarity is 1.0 - dist
            relevance = max(0.0, 1.0 - float(dist)) if dist is not None else 1.0
            
            if relevance < min_relevance:
                continue
                
            matches.append({
                "text": doc,
                "metadata": meta,
                "distance": float(dist) if dist is not None else 0.0,
                "relevance": round(relevance, 4)
            })
        
        # for doc, meta, dist in zip(docs, metas, distances):
        #     # For cosine distance, similarity is 1.0 - dist
        #     relevance = max(0.0, 1.0 - float(dist)) if dist is not None else 1.0
        #     matches.append({
        #         "text": doc,
        #         "metadata": meta,
        #         "distance": float(dist) if dist is not None else 0.0,
        #         "relevance": round(relevance, 4)
        #     })
            
    return matches


def _invalidate_file_cache() -> None:
    global _indexed_files
    _indexed_files = None


def list_indexed_files() -> Dict[str, str]:
    """Return {path: filename} for every file that has chunks in the collection."""
    global _indexed_files, _indexed_files_count
    collection = get_collection()
    count = collection.count()
    if _indexed_files is None or count != _indexed_files_count:
        metas = collection.get(include=["metadatas"]).get("metadatas") or []
        _indexed_files_count = count
        _indexed_files = {m["path"]: m.get("filename", os.path.basename(m["path"])) for m in metas if m and m.get("path")}
    return _indexed_files


def get_chunks(
    where: Optional[Dict[str, Any]] = None,
    where_document: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Fetch chunks by metadata / document-text filter (no vector search).
    Returns [{"text", "metadata", "embedding"}].
    """
    collection = get_collection()
    if collection.count() == 0:
        return []
    results = collection.get(
        where=where,
        where_document=where_document,
        limit=limit,
        include=["documents", "metadatas", "embeddings"]
    )
    docs = results.get("documents") or []
    metas = results.get("metadatas") or [{}] * len(docs)
    embs = results.get("embeddings")
    if embs is None:
        embs = [None] * len(docs)
    return [
        {"text": d, "metadata": m, "embedding": e}
        for d, m, e in zip(docs, metas, embs)
    ]


def prune_missing_files() -> Dict[str, Any]:
    """
    Delete chunks for every indexed file that no longer exists on disk.
    Returns {"files_removed": [paths], "chunks_removed": int}.
    """
    collection = get_collection()
    existing = collection.get(include=["metadatas"])
    ids = existing.get("ids") or []
    metas = existing.get("metadatas") or []

    stale_ids = []
    stale_paths = set()
    exists_cache: Dict[str, bool] = {}
    for chunk_id, meta in zip(ids, metas):
        path = (meta or {}).get("path", "")
        if path not in exists_cache:
            exists_cache[path] = bool(path) and os.path.exists(path)
        if not exists_cache[path]:
            stale_ids.append(chunk_id)
            stale_paths.add(path)

    # Delete in batches to stay well under ChromaDB's max batch size
    batch_size = 5000
    for i in range(0, len(stale_ids), batch_size):
        collection.delete(ids=stale_ids[i:i + batch_size])
    if stale_ids:
        _invalidate_file_cache()

    return {"files_removed": sorted(stale_paths), "chunks_removed": len(stale_ids)}


def get_total_chunks() -> int:
    """Return count of total chunks currently in vector collection."""
    try:
        collection = get_collection()
        return collection.count()
    except Exception:
        return 0

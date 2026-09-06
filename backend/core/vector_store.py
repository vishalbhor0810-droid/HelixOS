import os
import hashlib
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from backend.config import settings

_client = None
_collection = None


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
    return len(ids)


def query(query_embedding: List[float], top_k: int = None, where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Search collection for top_k nearest chunks to query_embedding.
    """
    if top_k is None:
        top_k = settings.SIMILARITY_TOP_K
        
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
            
            # ADD THIS LINE: Only keep matches that score 50% (0.50) or higher!
            if relevance < 0.50:
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


def get_total_chunks() -> int:
    """Return count of total chunks currently in vector collection."""
    try:
        collection = get_collection()
        return collection.count()
    except Exception:
        return 0

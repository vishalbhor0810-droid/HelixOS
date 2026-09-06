import os
from typing import List, Dict, Any, Optional, Tuple
from backend.core.embedder import embed_texts
from backend.core import vector_store
from backend.core import filesystem_search
from backend.models.schemas import SourceItem, ActionItem
from backend.config import settings


class HybridRetriever:
    def __init__(self):
        pass

    def retrieve(
        self,
        query: str,
        folder_path: Optional[str] = None,
        top_k: int = None
    ) -> Tuple[List[SourceItem], Optional[ActionItem], str]:
        """
        Execute hybrid search combining vector similarity and filesystem matching.
        Returns: (sources, primary_action, confidence_level)
        """
        if top_k is None:
            top_k = settings.SIMILARITY_TOP_K

        # 1. Embed query
        embeddings = embed_texts([query])
        if not embeddings:
            return [], None, "uncertain"

        query_emb = embeddings[0]

        # 2. Query ChromaDB for semantic matches
        raw_vector_matches = vector_store.query(query_emb, top_k=top_k)

        # 3. Query filesystem for filename matches
        fs_matches = filesystem_search.search_filesystem_by_name(query, folder_path=folder_path, max_results=5)

        verified_sources: List[SourceItem] = []
        seen_paths = set()
        highest_score = 0.0

        # Process vector matches
        for match in raw_vector_matches:
            meta = match.get("metadata", {})
            file_path = meta.get("path", "")
            
            # Verify file physically exists on disk
            if not os.path.exists(file_path):
                # Clean up stale vector store reference
                vector_store.delete_by_path(file_path)
                continue

            relevance = match.get("relevance", 0.0)
            highest_score = max(highest_score, relevance)

            source = SourceItem(
                filename=meta.get("filename", os.path.basename(file_path)),
                path=file_path,
                chunk_index=meta.get("chunk_index", 0),
                total_chunks=meta.get("total_chunks", 1),
                relevance_score=relevance,
                snippet=match.get("text", "")
            )
            verified_sources.append(source)
            seen_paths.add(file_path.lower())

        # Process filesystem filename matches that weren't in top vector hits
        # Process filesystem filename matches that weren't in top vector hits
        for fs in fs_matches:
            p_lower = fs["path"].lower()
            if p_lower not in seen_paths:
                
                # ADD THESE TWO LINES: Block bad filename matches too!
                if fs["score"] < 0.50:
                    continue
                    
                source = SourceItem(
                    filename=fs["filename"],
                    path=fs["path"],
                    chunk_index=0,
                    total_chunks=1,
                    relevance_score=min(0.85, fs["score"]),
                    snippet=f"File found matching search terms '{query}'"
                )
        # for fs in fs_matches:
        #     p_lower = fs["path"].lower()
        #     if p_lower not in seen_paths:
        #         source = SourceItem(
        #             filename=fs["filename"],
        #             path=fs["path"],
        #             chunk_index=0,
        #             total_chunks=1,
        #             relevance_score=min(0.85, fs["score"]),
        #             snippet=f"File found matching search terms '{query}'"
        #         )
                verified_sources.append(source)
                seen_paths.add(p_lower)

        # Sort verified sources in descending order of relevance score (highest percentage at the top)
        verified_sources.sort(key=lambda s: s.relevance_score, reverse=True)

        # Determine confidence
        confidence = "uncertain"
        if highest_score >= 0.75:
            confidence = "high"
        elif highest_score >= 0.50:
            confidence = "medium"
        elif verified_sources:
            confidence = "low"

        # Determine primary action (e.g. Open File)
        primary_action = None
        if verified_sources:
            best_match = verified_sources[0]
            primary_action = ActionItem(
                action_type="open_file",
                label=f"Open {best_match.filename}",
                payload={"path": best_match.path}
            )

        return verified_sources, primary_action, confidence


retriever = HybridRetriever()

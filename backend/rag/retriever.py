import os
import re
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional, Tuple, Set
import numpy as np
from backend.core.embedder import embed_texts
from backend.core import vector_store
from backend.core import filesystem_search
from backend.models.schemas import SourceItem, ActionItem
from backend.config import settings

# Re-ranking weights. Final score = vector similarity
#   + FILENAME_BOOST * (fraction of query terms found in the filename)
#   + KEYWORD_BOOST  * (fraction of query terms found in the chunk text)
# all-MiniLM-L6-v2 similarities for short keyword queries sit in a narrow ~0.2-0.4 band,
# so these boosts are what let exact term matches outrank loosely related chunks.
FILENAME_BOOST = 0.35
KEYWORD_BOOST = 0.25

# How many vector hits to pull before re-ranking (relative to top_k)
CANDIDATE_MULTIPLIER = 5
MIN_CANDIDATES = 25
# Max files whose chunks are pulled in because their filename matches the query
MAX_FILENAME_MATCH_FILES = 5
# Max chunks pulled in per query term by literal text match
MAX_KEYWORD_CHUNKS_PER_TERM = 50

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from",
    "give", "has", "have", "how", "i", "in", "is", "it", "its", "me", "my", "of", "on",
    "or", "please", "show", "tell", "that", "the", "this", "to", "was", "what", "where",
    "which", "who", "why", "with", "you", "your", "find", "open", "get", "about", "file",
    "files", "document", "documents", "doc", "pdf", "docx", "txt", "png", "jpg", "jpeg",
    "xlsx", "xlsm", "xls", "pptx", "ppt", "excel", "powerpoint", "spreadsheet",
    "spreadsheets", "slide", "slides",
    "contain", "contains", "containing", "related", "regarding", "list", "all", "any",
    "some", "there", "need", "want", "search", "look", "looking", "see", "mentions",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# File-type words in a query -> extensions to restrict results to ("which png has ..." -> .png only)
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
_TYPE_WORDS = {
    "pdf": {".pdf"},
    "docx": {".docx"},
    "txt": {".txt"},
    "md": {".md"}, "markdown": {".md"},
    "csv": {".csv"},
    "xlsx": {".xlsx", ".xlsm", ".xls"}, "xlsm": {".xlsm"}, "xls": {".xls"},
    "excel": {".xlsx", ".xlsm", ".xls"},
    "spreadsheet": {".xlsx", ".xlsm", ".xls", ".csv"},
    "pptx": {".pptx"}, "ppt": {".pptx"}, "powerpoint": {".pptx"},
    "png": {".png"}, "jpg": {".jpg", ".jpeg"}, "jpeg": {".jpg", ".jpeg"},
    "webp": {".webp"}, "bmp": {".bmp"}, "tiff": {".tiff"},
    "image": _IMAGE_EXTS, "screenshot": _IMAGE_EXTS, "photo": _IMAGE_EXTS, "picture": _IMAGE_EXTS,
}
# "word" alone is too common ("which file has the word X"), so only count it next to file/doc
_WORD_FILE_RE = re.compile(r"\bword\s+(?:file|doc|document)s?\b")
# Conversion targets ("convert x to pdf") name the output type, not the type being searched for
_TARGET_TYPE_RE = re.compile(r"\b(?:to|into|as)\s+(?:an?\s+)?\.?[a-z]+\b")


def _normalize(token: str) -> str:
    # Light stemming so "fees" matches "fee"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _tokenize(text: str) -> Set[str]:
    return {_normalize(t) for t in _TOKEN_RE.findall(text.lower())}


def _query_terms(query: str) -> List[str]:
    terms = []
    for t in _TOKEN_RE.findall(query.lower()):
        if t in _STOPWORDS or (len(t) < 3 and not t.isdigit()):
            continue
        t = _normalize(t)
        if t not in terms:
            terms.append(t)
    return terms


def _term_in(term: str, tokens: Set[str]) -> bool:
    """Exact match, or for longer terms a prefix / close-spelling match ("receipt" ~ "reciept")."""
    if term in tokens:
        return True
    if len(term) < 4:
        return False
    for tok in tokens:
        if len(tok) < 4:
            continue
        if tok.startswith(term) or term.startswith(tok):
            return True
        matcher = SequenceMatcher(None, term, tok)
        if matcher.quick_ratio() >= 0.8 and matcher.ratio() >= 0.8:
            return True
    return False


def _coverage(terms: List[str], tokens: Set[str]) -> float:
    if not terms:
        return 0.0
    return sum(1 for t in terms if _term_in(t, tokens)) / len(terms)


def _filename_tokens(filename: str) -> Set[str]:
    return _tokenize(os.path.splitext(filename)[0])


def _requested_extensions(query: str) -> Set[str]:
    """Extensions the user asked for by type ("which .png ...", "my excel files"); empty = no restriction."""
    q = _TARGET_TYPE_RE.sub(" ", query.lower())
    exts: Set[str] = set()
    if _WORD_FILE_RE.search(q):
        exts |= {".docx"}
    for t in _TOKEN_RE.findall(q):
        exts |= _TYPE_WORDS.get(_normalize(t), set()) or _TYPE_WORDS.get(t, set())
    return exts


def _has_ext(path: str, exts: Set[str]) -> bool:
    return not exts or os.path.splitext(path)[1].lower() in exts


def _contains_filter(term: str) -> Dict[str, Any]:
    # ChromaDB $contains is case-sensitive, so try common casings
    variants = list(dict.fromkeys([term, term.capitalize(), term.upper()]))
    if len(variants) == 1:
        return {"$contains": variants[0]}
    return {"$or": [{"$contains": v} for v in variants]}


class HybridRetriever:
    def __init__(self):
        pass

    def _collect_candidates(
        self, query_emb: List[float], terms: List[str], top_k: int, exts: Set[str]
    ) -> Tuple[Dict[Tuple[str, int], Dict[str, Any]], Dict[str, float]]:
        """
        Gather candidate chunks from three sources: vector search, filename matches, and
        literal keyword matches. Returns ({(path, chunk_index): candidate}, {path: filename_coverage}).
        """
        q = np.asarray(query_emb, dtype=np.float32)
        candidates: Dict[Tuple[str, int], Dict[str, Any]] = {}
        ext_where = {"extension": {"$in": sorted(exts)}} if exts else None

        def add(text: str, meta: Dict[str, Any], similarity: float):
            key = (meta.get("path", ""), meta.get("chunk_index", 0))
            if key not in candidates:
                candidates[key] = {"text": text, "metadata": meta, "similarity": similarity}

        def add_raw_chunks(chunks: List[Dict[str, Any]]):
            for c in chunks:
                emb = c.get("embedding")
                sim = float(np.dot(np.asarray(emb, dtype=np.float32), q)) if emb is not None else 0.0
                add(c["text"], c["metadata"], max(0.0, sim))

        # 1. Semantic: a wider pool than top_k so re-ranking has something to work with
        pool_k = max(top_k * CANDIDATE_MULTIPLIER, MIN_CANDIDATES)
        for m in vector_store.query(query_emb, top_k=pool_k, where=ext_where, min_relevance=0.0):
            add(m["text"], m["metadata"], m["relevance"])

        # 2. Filename: pull in chunks of indexed files whose name matches the query terms
        filename_scores: Dict[str, float] = {}
        if terms:
            for path, filename in vector_store.list_indexed_files().items():
                if not _has_ext(path, exts):
                    continue
                cov = _coverage(terms, _filename_tokens(filename))
                if cov > 0:
                    filename_scores[path] = cov
            best_files = sorted(filename_scores, key=filename_scores.get, reverse=True)[:MAX_FILENAME_MATCH_FILES]
            for path in best_files:
                add_raw_chunks(vector_store.get_chunks(where={"path": path}))

        # 3. Keyword: chunks that literally contain a query term
        for term in terms:
            if len(term) < 4 and not term.isdigit():
                continue
            add_raw_chunks(vector_store.get_chunks(
                where=ext_where, where_document=_contains_filter(term), limit=MAX_KEYWORD_CHUNKS_PER_TERM
            ))

        return candidates, filename_scores

    def retrieve(
        self,
        query: str,
        folder_path: Optional[str] = None,
        top_k: int = None
    ) -> Tuple[List[SourceItem], Optional[ActionItem], str]:
        """
        Execute hybrid search combining vector similarity, keyword and filename matching.
        Returns: (sources, primary_action, confidence_level)
        """
        if top_k is None:
            top_k = settings.SIMILARITY_TOP_K

        # 1. Embed query
        embeddings = embed_texts([query])
        if not embeddings:
            return [], None, "uncertain"

        query_emb = embeddings[0]
        terms = _query_terms(query)
        exts = _requested_extensions(query)

        # 2. Gather candidates from vector, filename and keyword search
        candidates, filename_scores = self._collect_candidates(query_emb, terms, top_k, exts)

        # 3. Re-rank: vector similarity + filename and keyword boosts
        scored: List[Tuple[float, Dict[str, Any]]] = []
        stale_paths = set()
        for cand in candidates.values():
            meta = cand["metadata"]
            file_path = meta.get("path", "")

            # Verify file physically exists on disk
            if file_path in stale_paths or not os.path.exists(file_path):
                stale_paths.add(file_path)
                continue

            fn_cov = filename_scores.get(file_path, 0.0)
            kw_cov = _coverage(terms, _tokenize(cand["text"]))
            score = min(1.0, cand["similarity"] + FILENAME_BOOST * fn_cov + KEYWORD_BOOST * kw_cov)
            if score < settings.SIMILARITY_THRESHOLD:
                continue
            scored.append((score, cand))

        # Clean up stale vector store references
        for path in stale_paths:
            vector_store.delete_by_path(path)

        scored.sort(key=lambda x: x[0], reverse=True)

        # Diversity rule: top_k distinct files, at most MAX_CHUNKS_PER_FILE chunks from each
        per_file: Dict[str, List[Tuple[float, Dict[str, Any]]]] = {}
        for score, cand in scored:
            file_path = cand["metadata"].get("path", "")
            if file_path in per_file:
                if len(per_file[file_path]) < settings.MAX_CHUNKS_PER_FILE:
                    per_file[file_path].append((score, cand))
            elif len(per_file) < top_k:
                per_file[file_path] = [(score, cand)]

        # One source per file: best chunk's score, chunk texts merged in document order
        verified_sources: List[SourceItem] = []
        seen_paths = set()
        for file_path, hits in per_file.items():
            best_score, best = hits[0]
            meta = best["metadata"]
            ordered = sorted(hits, key=lambda h: h[1]["metadata"].get("chunk_index", 0))
            verified_sources.append(SourceItem(
                filename=meta.get("filename", os.path.basename(file_path)),
                path=file_path,
                chunk_index=meta.get("chunk_index", 0),
                total_chunks=meta.get("total_chunks", 1),
                relevance_score=round(best_score, 4),
                snippet="\n...\n".join(h[1]["text"] for h in ordered)
            ))
            seen_paths.add(file_path.lower())

        # 4. Filename matches on disk for files that aren't indexed (no content to show)
        indexed_lower = {p.lower() for p in vector_store.list_indexed_files()}
        fs_matches = filesystem_search.search_filesystem_by_name(query, folder_path=folder_path, max_results=5)
        for fs in fs_matches:
            p_lower = fs["path"].lower()
            if p_lower in seen_paths or p_lower in indexed_lower or not _has_ext(fs["path"], exts):
                continue
            fn_cov = _coverage(terms, _filename_tokens(fs["filename"]))
            if fn_cov < 0.5:
                continue
            verified_sources.append(SourceItem(
                filename=fs["filename"],
                path=fs["path"],
                chunk_index=0,
                total_chunks=1,
                relevance_score=round(0.25 + FILENAME_BOOST * fn_cov, 4),
                snippet=f"File found matching search terms '{query}' (not indexed, content unavailable)"
            ))
            seen_paths.add(p_lower)

        # Sort verified sources in descending order of relevance score (highest at the top)
        verified_sources.sort(key=lambda s: s.relevance_score, reverse=True)
        highest_score = verified_sources[0].relevance_score if verified_sources else 0.0

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

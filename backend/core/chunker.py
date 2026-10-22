import re
from typing import List, Dict, Any
from backend.config import settings

_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?\n])\s+')


def _split_sentences(text: str) -> List[str]:
    raw_parts = _SENTENCE_SPLIT_RE.split(text)
    sentences = [s.strip() for s in raw_parts if s.strip()]
    return sentences


def _hard_slice(text: str, chunk_size: int, overlap: int) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += (chunk_size - overlap)
    return chunks


def chunk_text(text: str, chunk_size: int = None, chunk_overlap: int = None) -> List[Dict[str, Any]]:
    """
    Split text into overlapping, sentence-aware chunks.
    Returns a list of dicts: [{"text": str, "chunk_index": int, "total_chunks": int}]
    """
    if chunk_size is None:
        chunk_size = settings.CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = settings.CHUNK_OVERLAP
        
    text = text.strip()
    if not text:
        return []
        
    if len(text) <= chunk_size:
        return [{
            "text": text,
            "chunk_index": 0,
            "total_chunks": 1
        }]
        
    sentences = _split_sentences(text)
    if not sentences:
        raw_chunks = _hard_slice(text, chunk_size, chunk_overlap)
        total = len(raw_chunks)
        return [{"text": c, "chunk_index": i, "total_chunks": total} for i, c in enumerate(raw_chunks)]
        
    chunks = []
    current_chunk = []
    current_length = 0
    
    for sentence in sentences:
        if len(sentence) > chunk_size:
            # Handle oversized single sentence
            if current_chunk:
                merged = " ".join(current_chunk).strip()
                if merged:
                    chunks.append(merged)
                current_chunk = []
                current_length = 0
            sub_chunks = _hard_slice(sentence, chunk_size, chunk_overlap)
            chunks.extend(sub_chunks)
            continue
            
        if current_length + len(sentence) + 1 > chunk_size:
            merged = " ".join(current_chunk).strip()
            if merged:
                chunks.append(merged)
                
            # Build overlap from previous sentences
            overlap_acc = []
            overlap_len = 0
            for prev_sent in reversed(current_chunk):
                if overlap_len + len(prev_sent) + 1 <= chunk_overlap:
                    overlap_acc.insert(0, prev_sent)
                    overlap_len += len(prev_sent) + 1
                else:
                    break
            current_chunk = overlap_acc + [sentence]
            current_length = sum(len(s) for s in current_chunk) + len(current_chunk) - 1
        else:
            current_chunk.append(sentence)
            current_length += len(sentence) + 1
            
    if current_chunk:
        merged = " ".join(current_chunk).strip()
        if merged:
            chunks.append(merged)
            
    total_chunks = len(chunks)
    return [
        {
            "text": chunk,
            "chunk_index": idx,
            "total_chunks": total_chunks
        }
        for idx, chunk in enumerate(chunks)
    ]

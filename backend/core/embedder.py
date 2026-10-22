import os
from typing import List, Union
from sentence_transformers import SentenceTransformer
from backend.config import settings

_model_instance = None


def get_model() -> SentenceTransformer:
    global _model_instance
    if _model_instance is None:
        model_name = settings.EMBEDDING_MODEL
        # SentenceTransformer loads from local cache or HuggingFace
        _model_instance = SentenceTransformer(model_name)
    return _model_instance


def embed_texts(texts: Union[str, List[str]]) -> List[List[float]]:
    """Generate vector embeddings for text or list of texts."""
    if isinstance(texts, str):
        texts = [texts]
        
    if not texts:
        return []
        
    model = get_model()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()   # model.encode() returns numpy arrray  .tolist converts it to python  list

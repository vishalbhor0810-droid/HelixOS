import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)


class Settings:
    @property
    def HOST(self) -> str:
        return os.getenv("HOST", "127.0.0.1")

    @property
    def PORT(self) -> int:
        return int(os.getenv("PORT", "8000"))
    
    @property
    def LLM_PROVIDER(self) -> str:
        load_dotenv(BASE_DIR / ".env", override=True)
        return os.getenv("LLM_PROVIDER", "groq").lower()

    @property
    def LLM_API_KEY(self) -> str:
        load_dotenv(BASE_DIR / ".env", override=True)
        return os.getenv("LLM_API_KEY", "").strip()

    @property
    def LLM_MODEL(self) -> str:
        load_dotenv(BASE_DIR / ".env", override=True)
        return os.getenv("LLM_MODEL", "llama-3.1-8b-instant").strip()

    @property
    def LLM_BASE_URL(self) -> str:
        load_dotenv(BASE_DIR / ".env", override=True)
        return os.getenv("LLM_BASE_URL", "").strip()

    # Vision fallback for scanned pages local OCR can't read (e.g. handwriting)
    @property
    def VISION_FALLBACK(self) -> bool:
        load_dotenv(BASE_DIR / ".env", override=True)
        return os.getenv("VISION_FALLBACK", "true").strip().lower() in ("1", "true", "yes", "on")

    @property
    def VISION_MODEL(self) -> str:
        load_dotenv(BASE_DIR / ".env", override=True)
        return os.getenv("VISION_MODEL", "").strip()

    # Pages whose average EasyOCR confidence is below this are sent to the vision model
    VISION_MIN_CONFIDENCE: float = float(os.getenv("VISION_MIN_CONFIDENCE", "0.6"))
    # Cap on vision calls per document, to bound cost and time on long scans
    VISION_MAX_PAGES: int = int(os.getenv("VISION_MAX_PAGES", "20"))

    # Embedding and ChromaDB
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "chroma_db"))
    COLLECTION_NAME: str = "helix_documents"
    
    # Chunking
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    
    # Retrieval
    SIMILARITY_TOP_K: int = 4  # number of distinct files returned
    # Max chunks kept per file (merged into that file's single source entry)
    MAX_CHUNKS_PER_FILE: int = int(os.getenv("MAX_CHUNKS_PER_FILE", "2"))
    # Minimum cosine similarity (0-1) a chunk needs to be returned
    SIMILARITY_THRESHOLD: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.10"))


settings = Settings()

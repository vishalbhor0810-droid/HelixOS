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
        return os.getenv("LLM_MODEL", "llama-3.3-70b-versatile").strip()

    @property
    def LLM_BASE_URL(self) -> str:
        load_dotenv(BASE_DIR / ".env", override=True)
        return os.getenv("LLM_BASE_URL", "").strip()
    
    # Embedding and ChromaDB
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "chroma_db"))
    COLLECTION_NAME: str = "helix_documents"
    
    # Chunking
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    
    # Retrieval
    SIMILARITY_TOP_K: int = 4
    SIMILARITY_THRESHOLD: float = 1.2


settings = Settings()

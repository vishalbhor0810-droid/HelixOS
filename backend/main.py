import os
import sys
from contextlib import asynccontextmanager
import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings
from backend.api.routes import router as api_router
from backend.core import embedder, vector_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("helix.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing HelixOS Backend Services...")
    try:
        # Preload embedding model and vector store connection
        embedder.get_model()
        vector_store.get_collection()

        # Remove chunks for files deleted or moved while the app was closed
        pruned = vector_store.prune_missing_files()
        if pruned["chunks_removed"]:
            logger.info(
                f"Pruned {pruned['chunks_removed']} stale chunks from "
                f"{len(pruned['files_removed'])} missing files: {pruned['files_removed']}"
            )
        else:
            logger.info("Index is clean: all indexed files exist on disk.")

        logger.info(f"Vector store initialized. Current chunk count: {vector_store.get_total_chunks()}")
    except Exception as e:
        logger.error(f"Error during startup initialization: {e}", exc_info=True)
    yield
    logger.info("Shutting down HelixOS Backend...")


app = FastAPI(
    title="HelixOS AI Desktop Backend",
    description="Document Intelligence, RAG, and Desktop Agent Services for HelixOS",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for local Electron frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "service": "HelixOS AI Backend",
        "status": "online",
        "docs": "/docs"
    }


if __name__ == "__main__":
    logger.info(f"Starting HelixOS Backend on {settings.HOST}:{settings.PORT}")
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=False)

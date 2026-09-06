import logging
from fastapi import APIRouter, HTTPException
from backend.models.schemas import (
    ChatRequest,
    ChatResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    IndexFileRequest,
    IndexFileResponse,
    HealthResponse
)
from backend.rag.service import rag_service
from backend.rag.retriever import retriever
from backend.core.indexer import index_file, deindex_file
from backend.core import vector_store
from backend.rag.llm_client import llm_client
from backend.config import settings

logger = logging.getLogger("helix.api")
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    RAG-powered conversational endpoint for document search and questions.
    """
    try:
        response = await rag_service.answer_query(request)
        return response
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=SearchResponse)
async def search_endpoint(request: SearchRequest):
    """
    Execute semantic and filesystem search across indexed documents.
    """
    try:
        sources, _, _ = retriever.retrieve(
            query=request.query,
            folder_path=request.folder_path,
            top_k=request.top_k
        )
        
        results = [
            SearchResultItem(
                filename=s.filename,
                path=s.path,
                relevance_score=s.relevance_score,
                matched_by="hybrid",
                snippet=s.snippet
            )
            for s in sources
        ]
        
        return SearchResponse(query=request.query, results=results)
    except Exception as e:
        logger.error(f"Error in search endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/index/file", response_model=IndexFileResponse)
async def index_file_endpoint(request: IndexFileRequest):
    """
    Index or re-index a single document file.
    """
    try:
        result = index_file(request.file_path)
        return IndexFileResponse(
            status=result.get("status", "error"),
            filename=result.get("filename", ""),
            path=result.get("path", request.file_path),
            textLength=result.get("textLength", 0),
            chunksIndexed=result.get("chunksIndexed", 0),
            error=result.get("error")
        )
    except Exception as e:
        logger.error(f"Error indexing file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/index/file", response_model=IndexFileResponse)
async def deindex_file_endpoint(request: IndexFileRequest):
    """
    Remove indexed chunks of a file from vector storage.
    """
    try:
        result = deindex_file(request.file_path)
        return IndexFileResponse(
            status="deleted",
            filename="",
            path=result.get("path", request.file_path),
            textLength=0,
            chunksIndexed=0
        )
    except Exception as e:
        logger.error(f"Error deindexing file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_endpoint():
    """
    Health check and backend statistics.
    """
    total_chunks = vector_store.get_total_chunks()
    return HealthResponse(
        status="ok",
        total_chunks=total_chunks,
        llm_ready=llm_client.is_configured(),
        llm_provider=settings.LLM_PROVIDER,
        llm_model=settings.LLM_MODEL
    )

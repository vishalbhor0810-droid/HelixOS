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
    IndexMoveRequest,
    HealthResponse,
    ConvertFileRequest,
    ConvertFileResponse,
)
from backend.rag.service import rag_service
from backend.rag.retriever import retriever
from backend.core.indexer import index_file, deindex_file, move_file
from backend.core.converter import convert_file
from backend.core import vector_store
from backend.rag.llm_client import llm_client
from backend.config import settings
from backend.models.schemas import ConvertFileRequest, ConvertFileResponse
from backend.models.schemas import FileOperationRequest, FileOperationResponse
from backend.core.file_ops import execute_plan

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

#remove code if error occurs
@router.post("/convert", response_model=ConvertFileResponse)
def convert_endpoint(request: ConvertFileRequest):
    try:
        result = convert_file(
            source_path=request.source_path,
            target_format=request.target_format
        )

        return ConvertFileResponse(
            status=result.get("status", "error"),
            source_path=result.get("source_path", request.source_path),
            target_path=result.get("target_path"),
            error=result.get("error")
        )

    except Exception as e:
        logger.error(f"Error in conversion endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    
@router.post("/search", response_model=SearchResponse)
def search_endpoint(request: SearchRequest):
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
def index_file_endpoint(request: IndexFileRequest):
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
def deindex_file_endpoint(request: IndexFileRequest):
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


@router.post("/index/move", response_model=IndexFileResponse)
def move_index_endpoint(request: IndexMoveRequest):
    """
    Update the index after a file or folder is renamed/moved.
    """
    try:
        result = move_file(request.src_path, request.dest_path)
        return IndexFileResponse(
            status=result.get("status", "error"),
            filename=result.get("filename", ""),
            path=result.get("path", request.dest_path),
            textLength=result.get("textLength", 0),
            chunksIndexed=result.get("chunksIndexed", 0),
            chunksMoved=result.get("chunksMoved", 0),
            error=result.get("error")
        )
    except Exception as e:
        logger.error(f"Error moving indexed file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/execute", response_model=FileOperationResponse)
def execute_file_operation(request: FileOperationRequest):
    """
    Run a file plan the user confirmed in chat (create folder + move/copy files).
    """
    try:
        result = execute_plan(
            root=request.root,
            folder_name=request.folder,
            file_paths=request.files,
            mode=request.mode,
            sync_index=request.sync_index
        )
        return FileOperationResponse(**result)
    except Exception as e:
        logger.error(f"Error executing file operation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
def health_endpoint():
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

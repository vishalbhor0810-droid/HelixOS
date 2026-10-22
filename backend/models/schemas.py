from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'user', 'assistant', or 'system'")
    content: str = Field(..., description="Message text content")

class ChatRequest(BaseModel):
    message: str = Field(..., description="User prompt or query")
    history: List[ChatMessage] = Field(default_factory=list, description="Past conversation history")
    current_folder: Optional[str] = Field(default=None, description="Currently selected folder in Helix UI")
    recent_files: List[str] = Field(default_factory=list, description="Paths shown as sources in the previous answer")

class SourceItem(BaseModel):
    filename: str
    path: str
    chunk_index: int = 0
    total_chunks: int = 1
    relevance_score: float = 0.0
    snippet: str = ""

class ActionItem(BaseModel):
    action_type: str = Field(..., description="Action type, e.g. 'open_file', 'confirm_action', 'none'")
    label: str = Field(..., description="Human-readable button or action label")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Action parameters (e.g. {'path': '...'})")

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceItem] = Field(default_factory=list)
    action: Optional[ActionItem] = None
    confidence: str = Field(default="high", description="'high', 'medium', 'low', or 'uncertain'")

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    folder_path: Optional[str] = None

class SearchResultItem(BaseModel):
    filename: str
    path: str
    relevance_score: float
    matched_by: str = "semantic"  # "semantic", "filename", or "hybrid"
    snippet: str = ""

class SearchResponse(BaseModel):
    query: str
    results: List[SearchResultItem]

class IndexFileRequest(BaseModel):
    file_path: str

class IndexMoveRequest(BaseModel):
    src_path: str
    dest_path: str

class IndexFileResponse(BaseModel):
    status: str  # "success", "empty", "error", "unsupported", "deleted", "moved"
    filename: str
    path: str
    textLength: int = 0
    chunksIndexed: int = 0
    chunksMoved: int = 0
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str = "ok"
    total_chunks: int = 0
    llm_ready: bool = False
    llm_provider: str = ""
    llm_model: str = ""
class ConvertFileRequest(BaseModel):
    source_path: str = Field(..., description="Absolute path to the source file to convert")
    target_format: str = Field(..., description="Desired format without leading dot, e.g., 'pdf', 'txt'")

class FileOperationRequest(BaseModel):
    root: str = Field(..., description="Workspace folder all paths must stay inside")
    folder: str = Field(..., description="Name of the folder to create/use inside root")
    mode: str = Field(default="move", description="'move' or 'copy'")
    files: List[str] = Field(..., description="Absolute paths of files to move or copy")
    sync_index: bool = Field(default=True, description="Re-key indexed chunks after moving (skip when the watcher handles it)")

class FileOperationResult(BaseModel):
    file: str
    status: str  # "done", "skipped", "error"
    dest: Optional[str] = None
    renamed: bool = False
    error: Optional[str] = None

class FileOperationResponse(BaseModel):
    status: str  # "success", "partial", "error"
    folder_path: Optional[str] = None
    created_folder: bool = False
    mode: str = "move"
    results: List[FileOperationResult] = Field(default_factory=list)
    error: Optional[str] = None

class ConvertFileResponse(BaseModel):
    status: str = Field(..., description="'success' or 'error'")
    source_path: str = Field(..., description="Original file path")
    target_path: Optional[str] = Field(default=None, description="Path to the new file when conversion succeeds")
    error: Optional[str] = Field(default=None, description="Error message if conversion fails")

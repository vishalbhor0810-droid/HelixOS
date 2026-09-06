from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'user', 'assistant', or 'system'")
    content: str = Field(..., description="Message text content")

class ChatRequest(BaseModel):
    message: str = Field(..., description="User prompt or query")
    history: List[ChatMessage] = Field(default_factory=list, description="Past conversation history")
    current_folder: Optional[str] = Field(default=None, description="Currently selected folder in Helix UI")

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

class IndexFileResponse(BaseModel):
    status: str  # "success", "empty", "error", "unsupported", "deleted"
    filename: str
    path: str
    textLength: int = 0
    chunksIndexed: int = 0
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str = "ok"
    total_chunks: int = 0
    llm_ready: bool = False
    llm_provider: str = ""
    llm_model: str = ""

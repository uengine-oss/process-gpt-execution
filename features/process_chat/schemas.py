from pydantic import BaseModel
from typing import List, Dict, Any
class ChatRequest(BaseModel):
    vendor: str
    model: str
    messages: List[Dict[str, Any]] 
    stream: bool = False
    modelConfig: Dict[str, Any]

class TokenCountRequest(BaseModel):
    vendor: str
    model: str
    messages: List[Dict[str, Any]]

class EmbeddingRequest(BaseModel):
    vendor: str
    model: str
    text: str
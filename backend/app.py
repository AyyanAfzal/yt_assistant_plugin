from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import sys
import uvicorn
import json

# Ensure parent directory is in sys.path for relative imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.youtube_rag_service import YouTubeRAGService

app = FastAPI(
    title="YouTube RAG API Service",
    description="Production-grade API for chatting with YouTube videos and obtaining timestamped summaries.",
    version="2.0.0"
)

# Enable CORS for Chrome Extension & local dev environments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global RAG Service instance
rag_service: Optional[YouTubeRAGService] = None

def get_rag_service() -> YouTubeRAGService:
    global rag_service
    if rag_service is None:
        rag_service = YouTubeRAGService()
    return rag_service

class ChatRequest(BaseModel):
    url_or_id: str = Field(..., description="YouTube video URL or Video ID", example="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    question: str = Field(..., description="User question about the video content", example="What is the main topic of this video?")

class SourceItem(BaseModel):
    timestamp: str
    seconds: int
    snippet: str

class ChatResponse(BaseModel):
    video_id: str
    answer: str
    sources: List[SourceItem]

class SummaryRequest(BaseModel):
    url_or_id: str = Field(..., description="YouTube video URL or Video ID")

class SummaryResponse(BaseModel):
    video_id: str
    summary: str

@app.get("/")
def read_root():
    return {"status": "online", "message": "YouTube RAG Assistant API is running."}

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "YouTube RAG Engine"}

@app.post("/api/chat", response_model=ChatResponse)
def chat_with_video(req: ChatRequest):
    try:
        service = get_rag_service()
        result = service.answer_question(req.url_or_id, req.question)
        return ChatResponse(
            video_id=result["video_id"],
            answer=result["answer"],
            sources=[SourceItem(**s) for s in result["sources"]]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/api/stream/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for streaming chat with memory.
    Client should send JSON: {"url_or_id": "...", "question": "...", "chat_history": [{"role": "user", "content": "..."}]}
    """
    await websocket.accept()
    service = get_rag_service()
    try:
        while True:
            data = await websocket.receive_text()
            req = json.loads(data)
            
            url_or_id = req.get("url_or_id")
            question = req.get("question")
            chat_history = req.get("chat_history", [])
            
            if not url_or_id or not question:
                await websocket.send_json({"error": "Missing url_or_id or question"})
                continue
                
            try:
                await websocket.send_json({"status": "thinking"})
                # Iterate through the async generator and stream chunks
                async for chunk in service.stream_answer(url_or_id, question, chat_history):
                    await websocket.send_json({"chunk": chunk})
                
                # Signal completion
                await websocket.send_json({"done": True})
            except Exception as e:
                await websocket.send_json({"error": str(e)})
    except WebSocketDisconnect:
        print("Client disconnected")

@app.post("/api/summary", response_model=SummaryResponse)
def summarize_video(req: SummaryRequest):
    try:
        service = get_rag_service()
        result = service.summarize_video(req.url_or_id)
        return SummaryResponse(
            video_id=result["video_id"],
            summary=result["summary"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)

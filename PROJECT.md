# Project: YouTube RAG Assistant Codebase Optimization

## Architecture
- Backend service: FastAPI application in `backend/app.py`
- RAG engine: `backend/youtube_rag_service.py`
- Vector Store: `PineconeVectorStore` (Pinecone integration)
- Embeddings: `GoogleGenerativeAIEmbeddings` (Gemini embeddings)

## Code Layout
- `backend/app.py`: FastAPI server endpoints (e.g. `/api/health`, `/api/query`, `/api/index`)
- `backend/youtube_rag_service.py`: YouTube transcript fetching, chunking, indexing, and retrieval logic
- `run_server.py`: Server launcher script

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Exploration & Impact Analysis | Map FAISS, BM25, HuggingFace usages across backend | None | DONE |
| 2 | Legacy Code Removal & Architecture Streamlining | Remove FAISS/BM25/HF code and streamline Pinecone + Gemini | M1 | DONE |
| 3 | General Cleanup & Import Hygiene | Clean unused imports, dead variables, and obsolete helpers | M2 | DONE |
| 4 | Verification & Audit | Boot server, test GET /api/health, run forensic integrity check | M3 | DONE |
| 5 | Victory Claim | Compile victory report and notify Sentinel | M4 | DONE |

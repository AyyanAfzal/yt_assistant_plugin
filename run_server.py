import uvicorn
import os
import sys

# Add project root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("Launching YouTube RAG FastAPI Server on http://localhost:8000 ...")
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=True)

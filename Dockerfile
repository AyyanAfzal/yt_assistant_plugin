FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required for native extensions and media utilities
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from requirements.txt
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# Expose FastAPI port
EXPOSE 8000

# Run Uvicorn Server
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]

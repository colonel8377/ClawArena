FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Build context is repository root in Railway and docker-compose.
# Copy backend source into /app so runtime import path stays consistent.
COPY backend/ ./

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn main:asgi_app --host 0.0.0.0 --port ${PORT:-8000}"]
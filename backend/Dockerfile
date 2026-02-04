# Production Dockerfile for Arena Poker Backend
#
# Features:
# - Multi-stage build for smaller image
# - Python 3.11 slim base image
# - Production-ready configuration
#
# Usage:
#   docker build -t arena-backend -f backend/Dockerfile .
#   docker run -p 8000:8000 --env-file .env arena-backend
#
# Note: Build from the repository root directory, not from backend/

# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements from root and install
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# Stage 2: Production image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY backend/ .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash arena \
    && chown -R arena:arena /app
USER arena

# Expose the application port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with production settings (no reload)
CMD ["uvicorn", "main:asgi_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

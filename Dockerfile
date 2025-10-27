# syntax=docker/dockerfile:1.7-labs
FROM python:3.12 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for SSL/certs and timezone
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY main.py README.md ./

# Default envs (can be overridden at runtime)
ENV POLL_INTERVAL=60 \
    STATE_FILE=/data/state.json

# Data directory for state persistence
VOLUME ["/data"]

CMD ["python", "main.py"]

# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — Publisher Service (Docker Compose bonus)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL description="Publisher Service untuk Pub-Sub Log Aggregator"

WORKDIR /app

# Non-root user
RUN adduser --disabled-password --gecos '' publisher \
    && chown -R publisher:publisher /app

# Dependency caching (hanya httpx untuk publisher)
COPY requirements-publisher.txt ./
RUN pip install --no-cache-dir -r requirements-publisher.txt

# Source code publisher
COPY publisher/ ./publisher/

USER publisher

ENV AGGREGATOR_URL=http://aggregator:8080 \
    TOTAL_EVENTS=5000 \
    DUPLICATE_RATE=0.25 \
    BATCH_SIZE=100 \
    BATCH_DELAY=0.05

# Publisher berjalan sekali lalu selesai (bukan server)
CMD ["python", "-m", "publisher.publisher"]

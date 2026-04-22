# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — Pub-Sub Log Aggregator (UTS Sistem Terdistribusi)
# ─────────────────────────────────────────────────────────────────────────────
# Base image: python:3.11-slim (sesuai rekomendasi soal)
FROM python:3.11-slim

# Metadata
LABEL maintainer="UTS Sistem Terdistribusi"
LABEL description="Pub-Sub Log Aggregator dengan Idempotent Consumer & Deduplication"

WORKDIR /app

# ── Security: non-root user ───────────────────────────────────────────────────
# Buat user appuser tanpa password dan buat direktori data
RUN adduser --disabled-password --gecos '' appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

# ── Dependency caching ────────────────────────────────────────────────────────
# Copy requirements dulu (sebelum source code) untuk memanfaatkan Docker layer cache.
# Layer ini hanya rebuild jika requirements.txt berubah.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ── Source code ───────────────────────────────────────────────────────────────
COPY src/ ./src/

# ── Runtime config ─────────────────────────────────────────────────────────
USER appuser

# Volume untuk dedup store yang persistent
VOLUME ["/app/data"]

# Port yang diexpose
EXPOSE 8080

# Environment defaults (dapat dioverride saat docker run)
ENV DEDUP_DB_PATH=/app/data/dedup.db \
    PORT=8080 \
    HOST=0.0.0.0 \
    LOG_LEVEL=INFO \
    QUEUE_MAXSIZE=10000

# Health check — cek setiap 30 detik, timeout 10 detik
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" \
    || exit 1

# Entry point: jalankan aggregator sebagai module
CMD ["python", "-m", "src.main"]

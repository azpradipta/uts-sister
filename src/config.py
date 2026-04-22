"""
Konfigurasi terpusat untuk Pub-Sub Log Aggregator.
Semua nilai dapat dioverride melalui environment variable.
"""
import os

# Path database SQLite untuk dedup store (persistent)
DEDUP_DB_PATH: str = os.getenv("DEDUP_DB_PATH", "/app/data/dedup.db")

# Ukuran maksimum in-memory queue
QUEUE_MAXSIZE: int = int(os.getenv("QUEUE_MAXSIZE", "10000"))

# Host dan Port server
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8080"))

# Log level
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

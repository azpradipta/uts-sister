"""
Dedup Store berbasis SQLite untuk Pub-Sub Log Aggregator.

Menjamin idempotency: event dengan kombinasi (topic, event_id) yang sama
hanya disimpan satu kali, meskipun diterima berkali-kali (at-least-once delivery).

Desain:
- SQLite dipilih karena embedded, tidak butuh server eksternal, dan mendukung
  ACID transactions → atomicity pada dedup check + insert dalam satu operasi.
- PRIMARY KEY (topic, event_id) di level database → collision langsung gagal
  dengan IntegrityError, tidak perlu SELECT-lalu-INSERT yang race-condition prone.
- threading.Lock() memastikan thread-safety saat dipanggil dari asyncio.to_thread().
- Persistent: selama file .db tidak dihapus, dedup tetap efektif setelah restart.

Referensi: Tanenbaum & Van Steen (2007), Bab 6 (Fault Tolerance) dan Bab 7 (Consistency).
"""
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DedupStore:
    """
    Persistent deduplication store menggunakan SQLite.

    Thread-safe: menggunakan threading.Lock() untuk melindungi akses concurrent.
    Idempotent: INSERT dengan PRIMARY KEY (topic, event_id) akan gagal atomically
    jika event sudah ada, sehingga tidak ada window race condition.
    """

    def __init__(self, db_path: str = "/app/data/dedup.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_directory()
        self._init_db()
        logger.info(f"DedupStore initialized | DB: {self.db_path}")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ensure_directory(self) -> None:
        """Buat direktori parent jika belum ada."""
        dir_path = os.path.dirname(self.db_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Buat koneksi SQLite baru (setiap operasi buat koneksi sendiri untuk keamanan thread)."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")   # Write-Ahead Logging untuk concurrency lebih baik
        conn.execute("PRAGMA synchronous=NORMAL")  # Keseimbangan performa vs durabilitas
        return conn

    def _init_db(self) -> None:
        """Inisialisasi skema database jika belum ada."""
        with self._lock:
            conn = self._connect()
            try:
                # Tabel utama: menyimpan event yang sudah diproses
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS processed_events (
                        topic        TEXT NOT NULL,
                        event_id     TEXT NOT NULL,
                        timestamp    TEXT NOT NULL,
                        source       TEXT NOT NULL,
                        payload      TEXT NOT NULL DEFAULT '{}',
                        processed_at TEXT NOT NULL,
                        PRIMARY KEY (topic, event_id)
                    )
                """)
                # Index untuk query GET /events?topic=...
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_topic
                    ON processed_events(topic)
                """)

                # Tabel statistik
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS stats (
                        key   TEXT PRIMARY KEY,
                        value INTEGER NOT NULL DEFAULT 0
                    )
                """)
                # Inisialisasi counter jika belum ada
                for key in ("received", "unique_processed", "duplicate_dropped"):
                    conn.execute(
                        "INSERT OR IGNORE INTO stats (key, value) VALUES (?, 0)",
                        (key,),
                    )
                conn.commit()
                logger.debug("Database schema initialized")
            finally:
                conn.close()

    # ── Public API ────────────────────────────────────────────────────────────

    def store_event(self, event: Dict[str, Any]) -> bool:
        """
        Coba simpan event ke database secara atomik.

        Menggunakan INSERT dengan PRIMARY KEY constraint:
        - Jika berhasil → event unik, counter unique_processed naik.
        - Jika IntegrityError → event duplikat, counter duplicate_dropped naik.

        Returns:
            True  → event berhasil disimpan (bukan duplikat)
            False → event adalah duplikat, diabaikan
        """
        topic = event.get("topic", "unknown")
        event_id = event.get("event_id", "unknown")

        with self._lock:
            conn = self._connect()
            try:
                try:
                    conn.execute(
                        """
                        INSERT INTO processed_events
                            (topic, event_id, timestamp, source, payload, processed_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            topic,
                            event_id,
                            event.get("timestamp", ""),
                            event.get("source", ""),
                            json.dumps(event.get("payload", {})),
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                    conn.execute(
                        "UPDATE stats SET value = value + 1 WHERE key = 'unique_processed'"
                    )
                    conn.commit()
                    return True  # event unik → diproses

                except sqlite3.IntegrityError:
                    # PRIMARY KEY violation → event duplikat
                    conn.execute(
                        "UPDATE stats SET value = value + 1 WHERE key = 'duplicate_dropped'"
                    )
                    conn.commit()
                    logger.warning(
                        f"⚠️  DUPLICATE | topic={topic} | event_id={event_id}"
                    )
                    return False  # duplikat → dibuang

            finally:
                conn.close()

    def increment_received(self, count: int = 1) -> None:
        """Tambah counter received sebanyak count."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE stats SET value = value + ? WHERE key = 'received'",
                    (count,),
                )
                conn.commit()
            finally:
                conn.close()

    def get_events(self, topic: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Ambil semua event unik yang sudah diproses.
        Jika topic diberikan, filter hanya event bertopik tersebut.
        """
        with self._lock:
            conn = self._connect()
            try:
                if topic:
                    cursor = conn.execute(
                        """
                        SELECT topic, event_id, timestamp, source, payload, processed_at
                        FROM processed_events
                        WHERE topic = ?
                        ORDER BY processed_at ASC
                        """,
                        (topic,),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT topic, event_id, timestamp, source, payload, processed_at
                        FROM processed_events
                        ORDER BY processed_at ASC
                        """
                    )
                rows = cursor.fetchall()
                return [
                    {
                        "topic": row[0],
                        "event_id": row[1],
                        "timestamp": row[2],
                        "source": row[3],
                        "payload": json.loads(row[4]),
                        "processed_at": row[5],
                    }
                    for row in rows
                ]
            finally:
                conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Ambil statistik lengkap aggregator dari database."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute("SELECT key, value FROM stats")
                stats = {row[0]: row[1] for row in cursor.fetchall()}

                cursor = conn.execute(
                    "SELECT DISTINCT topic FROM processed_events ORDER BY topic"
                )
                stats["topics"] = [row[0] for row in cursor.fetchall()]
                return stats
            finally:
                conn.close()

    def is_duplicate(self, topic: str, event_id: str) -> bool:
        """
        Cek apakah event sudah diproses (tanpa menyimpan).
        Digunakan untuk testing dan observability.
        """
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "SELECT 1 FROM processed_events WHERE topic = ? AND event_id = ?",
                    (topic, event_id),
                )
                return cursor.fetchone() is not None
            finally:
                conn.close()

"""
Idempotent Consumer untuk Pub-Sub Log Aggregator.

Consumer membaca event dari asyncio.Queue secara terus-menerus dan
memprosesnya melalui DedupStore. Jika event sudah pernah diproses
(berdasarkan topic + event_id), event tersebut dibuang (idempotent).

Desain:
- asyncio.Queue sebagai pipeline buffer antara publisher (HTTP handler) dan consumer.
- asyncio.to_thread() digunakan untuk operasi SQLite agar tidak memblokir event loop.
- Toleran terhadap crash: DedupStore persistent di SQLite → restart tidak mereset state.

Referensi: Tanenbaum & Van Steen (2007), Bab 3 (Communication) & Bab 6 (Fault Tolerance).
"""
import asyncio
import logging
from typing import Any, Dict

from .dedup_store import DedupStore

logger = logging.getLogger(__name__)


class IdempotentConsumer:
    """
    Consumer yang bersifat idempotent: setiap event dengan kombinasi
    (topic, event_id) yang sama hanya diproses tepat satu kali,
    sekalipun dikirim berkali-kali (at-least-once delivery scenario).
    """

    def __init__(self, queue: asyncio.Queue, dedup_store: DedupStore) -> None:
        self.queue = queue
        self.dedup_store = dedup_store
        self._running: bool = False
        self._total_processed: int = 0
        self._total_dropped: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Loop utama consumer. Berjalan sebagai asyncio background task.
        Menggunakan timeout 1 detik pada queue.get() agar loop dapat
        mengecek flag _running secara periodik.
        """
        self._running = True
        logger.info("🔄 IdempotentConsumer started — listening on queue...")

        while self._running:
            try:
                # Tunggu event dari queue (dengan timeout agar bisa cek _running)
                event: Dict[str, Any] = await asyncio.wait_for(
                    self.queue.get(), timeout=1.0
                )
                await self._process_event(event)
                self.queue.task_done()

            except asyncio.TimeoutError:
                # Normal: queue kosong, lanjut loop
                continue

            except asyncio.CancelledError:
                logger.info("Consumer task cancelled — stopping gracefully")
                break

            except Exception as exc:
                logger.error(f"Unexpected consumer error: {exc}", exc_info=True)

        logger.info(
            f"Consumer stopped | processed={self._total_processed} | "
            f"dropped={self._total_dropped}"
        )

    def stop(self) -> None:
        """Beri sinyal agar consumer berhenti setelah event saat ini selesai."""
        self._running = False
        logger.info("Consumer stop signal sent")

    # ── Event processing ──────────────────────────────────────────────────────

    async def _process_event(self, event: Dict[str, Any]) -> None:
        """
        Proses satu event:
        1. Coba simpan ke DedupStore (operasi berjalan di thread pool).
        2. Jika berhasil → log sebagai PROCESSED.
        3. Jika gagal (duplikat) → log sebagai DUPLICATE DROPPED.

        asyncio.to_thread() digunakan agar operasi SQLite synchronous tidak
        memblokir event loop Python.
        """
        topic = event.get("topic", "unknown")
        event_id = event.get("event_id", "unknown")

        # Jalankan operasi SQLite di thread terpisah untuk tidak blokir event loop
        stored: bool = await asyncio.to_thread(self.dedup_store.store_event, event)

        if stored:
            self._total_processed += 1
            logger.info(
                f"✅ PROCESSED  | topic={topic:<20} | event_id={event_id} "
                f"| session_total={self._total_processed}"
            )
        else:
            self._total_dropped += 1
            logger.warning(
                f"⚠️  DUPLICATE  | topic={topic:<20} | event_id={event_id} "
                f"| session_drops={self._total_dropped}"
            )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def session_processed(self) -> int:
        return self._total_processed

    @property
    def session_dropped(self) -> int:
        return self._total_dropped

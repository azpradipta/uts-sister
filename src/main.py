"""
FastAPI application untuk Pub-Sub Log Aggregator.

Arsitektur:
  Publisher → POST /publish → asyncio.Queue → IdempotentConsumer → SQLite DedupStore
                                                      ↓
                              GET /events & GET /stats ← DedupStore

Endpoint:
  POST /publish          — terima single event atau batch
  GET  /events?topic=... — list event unik yang sudah diproses
  GET  /stats            — statistik sistem (received, processed, dropped, uptime)
  GET  /health           — health check

Referensi: Tanenbaum & Van Steen (2007), Bab 1–7.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .consumer import IdempotentConsumer
from .dedup_store import DedupStore
from .models import Event, EventBatch

# ── Logging setup ─────────────────────────────────────────────────────────────
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

# ── Global state (diinisialisasi saat lifespan startup) ───────────────────────
_dedup_store: Optional[DedupStore] = None
_event_queue: Optional[asyncio.Queue] = None
_consumer: Optional[IdempotentConsumer] = None
_consumer_task: Optional[asyncio.Task] = None
_start_time: datetime = datetime.now(timezone.utc)


# ── Lifespan (startup & shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: inisialisasi DedupStore, Queue, dan Consumer.
    Shutdown: hentikan consumer dengan graceful.
    """
    global _dedup_store, _event_queue, _consumer, _consumer_task, _start_time

    # ── Startup ───────────────────────────────────────────────────────────────
    _start_time = datetime.now(timezone.utc)

    db_path = os.getenv("DEDUP_DB_PATH", "/app/data/dedup.db")
    queue_maxsize = int(os.getenv("QUEUE_MAXSIZE", "10000"))

    logger.info("🚀 Starting Pub-Sub Log Aggregator...")
    logger.info(f"   DB path     : {db_path}")
    logger.info(f"   Queue max   : {queue_maxsize}")

    _dedup_store = DedupStore(db_path=db_path)
    _event_queue = asyncio.Queue(maxsize=queue_maxsize)
    _consumer = IdempotentConsumer(queue=_event_queue, dedup_store=_dedup_store)
    _consumer_task = asyncio.create_task(_consumer.start(), name="idempotent-consumer")

    logger.info("✅ Aggregator ready — waiting for events")

    yield  # ← aplikasi berjalan di sini

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("🛑 Shutdown signal received — stopping consumer...")
    _consumer.stop()
    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    logger.info("👋 Aggregator shutdown complete")


# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Pub-Sub Log Aggregator",
    description=(
        "**UTS Sistem Terdistribusi** — Layanan Pub-Sub dengan Idempotent Consumer "
        "dan Deduplication berbasis SQLite.\n\n"
        "Publisher mengirim event ke `/publish`; consumer memproses secara idempotent "
        "sehingga event dengan `(topic, event_id)` yang sama hanya diproses sekali."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/publish", status_code=202, summary="Publish event ke aggregator")
async def publish(request: Request) -> Dict[str, Any]:
    """
    Terima satu atau banyak event dari publisher.

    Format yang diterima:
    - **Single event**: `{ "topic": "...", "event_id": "...", ... }`
    - **Batch object**: `{ "events": [ {...}, {...} ] }`
    - **Batch array**: `[ {...}, {...} ]`

    Semua event yang masuk dimasukkan ke asyncio.Queue untuk diproses
    secara asynchronous oleh IdempotentConsumer.
    """
    # Parse raw JSON agar bisa handle single/batch/array
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body harus JSON yang valid")

    # Normalisasi ke list of Event
    events: list[Event] = []
    try:
        if isinstance(body, list):
            # Format array langsung
            events = [Event(**e) for e in body]
        elif isinstance(body, dict):
            if "events" in body:
                # Format batch object
                batch = EventBatch(**body)
                events = batch.events
            else:
                # Format single event
                events = [Event(**body)]
        else:
            raise HTTPException(
                status_code=400,
                detail="Body harus JSON object (single/batch) atau array event"
            )
    except ValidationError as exc:
        # Pydantic v2 errors bisa mengandung objek Python (mis. ValueError di 'ctx')
        # yang tidak bisa di-JSON-serialize. Hanya ambil field yang aman.
        SAFE_KEYS = {"type", "loc", "msg", "input", "url"}
        errors = [
            {k: (str(v) if k == "loc" else v)
             for k, v in err.items()
             if k in SAFE_KEYS}
            for err in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=errors)

    if not events:
        raise HTTPException(status_code=400, detail="Tidak ada event yang diberikan")

    # Update counter received (async, non-blocking)
    await asyncio.to_thread(_dedup_store.increment_received, len(events))

    # Masukkan ke queue
    queued = 0
    for event in events:
        try:
            _event_queue.put_nowait(event.model_dump())
            queued += 1
        except asyncio.QueueFull:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Queue penuh ({_event_queue.maxsize} item). "
                    f"Berhasil di-queue: {queued}/{len(events)}. Coba lagi."
                ),
            )

    logger.info(
        f"📥 Accepted {queued} event(s) | queue_size={_event_queue.qsize()}"
    )

    return {
        "status": "accepted",
        "queued": queued,
        "total": len(events),
        "queue_size": _event_queue.qsize(),
    }


@app.get("/events", summary="Daftar event unik yang telah diproses")
async def get_events(topic: Optional[str] = None) -> Dict[str, Any]:
    """
    Kembalikan daftar event unik yang sudah diproses oleh consumer.

    Query parameter:
    - `topic` (opsional): filter event berdasarkan nama topik
    """
    events = await asyncio.to_thread(_dedup_store.get_events, topic)
    return {
        "topic": topic,
        "count": len(events),
        "events": events,
    }


@app.get("/stats", summary="Statistik sistem aggregator")
async def get_stats() -> Dict[str, Any]:
    """
    Kembalikan statistik real-time aggregator:
    - `received`: total event yang diterima via /publish
    - `unique_processed`: event unik yang berhasil diproses
    - `duplicate_dropped`: event duplikat yang dibuang
    - `duplicate_rate_pct`: persentase duplikat dari total received
    - `topics`: daftar topik aktif
    - `uptime_seconds`: waktu berjalan sejak startup
    - `queue_size`: jumlah event yang masih menunggu di queue
    """
    stats = await asyncio.to_thread(_dedup_store.get_stats)
    uptime = (datetime.now(timezone.utc) - _start_time).total_seconds()

    received = stats.get("received", 0)
    dropped = stats.get("duplicate_dropped", 0)
    duplicate_rate = (dropped / received * 100) if received > 0 else 0.0

    return {
        "received": received,
        "unique_processed": stats.get("unique_processed", 0),
        "duplicate_dropped": dropped,
        "duplicate_rate_pct": round(duplicate_rate, 2),
        "topics": stats.get("topics", []),
        "uptime_seconds": round(uptime, 2),
        "queue_size": _event_queue.qsize() if _event_queue else 0,
    }


@app.get("/health", summary="Health check")
async def health() -> Dict[str, Any]:
    """Endpoint untuk health check Docker dan monitoring."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queue_size": _event_queue.qsize() if _event_queue else 0,
    }


# ── Entry point (python -m src.main) ─────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))

    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        log_level=_log_level.lower(),
        reload=False,
    )

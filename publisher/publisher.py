"""
Publisher Service untuk Pub-Sub Log Aggregator.

Berjalan sebagai service terpisah dalam Docker Compose.
Mensimulasikan at-least-once delivery dengan mengirim duplikat intentional.

Skenario yang di-demo:
1. Tunggu aggregator siap (health check polling)
2. Kirim 5.000 event dengan 25% duplikasi
3. Tampilkan statistik akhir dari aggregator

Referensi: Tanenbaum & Van Steen (2007), Bab 3 (Communication) & Bab 6 (Fault Tolerance).
"""
import json
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] publisher — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("publisher")

# ── Config dari environment ───────────────────────────────────────────────────
AGGREGATOR_URL: str = os.getenv("AGGREGATOR_URL", "http://aggregator:8080")
TOTAL_EVENTS: int = int(os.getenv("TOTAL_EVENTS", "5000"))
DUPLICATE_RATE: float = float(os.getenv("DUPLICATE_RATE", "0.25"))
BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "100"))
BATCH_DELAY: float = float(os.getenv("BATCH_DELAY", "0.05"))  # detik antar batch

TOPICS = ["orders", "payments", "inventory", "user-events", "notifications", "audit-log"]


# ── Helper functions ──────────────────────────────────────────────────────────

def make_event(topic: str, event_id: str = None) -> dict[str, Any]:
    """Buat satu event dengan format yang valid."""
    return {
        "topic": topic,
        "event_id": event_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "publisher-service",
        "payload": {
            "value": random.randint(1, 100_000),
            "action": random.choice(["create", "update", "delete", "read", "retry"]),
            "user_id": random.randint(1, 10_000),
            "session": str(uuid.uuid4())[:8],
        },
    }


def wait_for_aggregator(url: str, max_retries: int = 30, delay: float = 2.0) -> None:
    """Polling health check sampai aggregator siap."""
    logger.info(f"Menunggu aggregator di {url}...")
    for attempt in range(1, max_retries + 1):
        try:
            resp = httpx.get(f"{url}/health", timeout=5.0)
            if resp.status_code == 200:
                logger.info(f"✅ Aggregator siap setelah {attempt} percobaan")
                return
        except httpx.RequestError as exc:
            logger.info(f"Percobaan {attempt}/{max_retries}: {exc}")
        time.sleep(delay)

    logger.error("❌ Aggregator tidak dapat dijangkau setelah max retries")
    sys.exit(1)


def send_batch(client: httpx.Client, events: list[dict]) -> bool:
    """Kirim satu batch events ke /publish. Return True jika berhasil."""
    try:
        resp = client.post(
            f"{AGGREGATOR_URL}/publish",
            json=events,
            timeout=30.0,
        )
        if resp.status_code == 202:
            return True
        logger.warning(f"Publish gagal: {resp.status_code} — {resp.text[:200]}")
        return False
    except httpx.RequestError as exc:
        logger.error(f"Request error: {exc}")
        return False


def print_stats(client: httpx.Client) -> None:
    """Ambil dan tampilkan statistik dari aggregator."""
    try:
        resp = client.get(f"{AGGREGATOR_URL}/stats", timeout=10.0)
        stats = resp.json()
        logger.info("=" * 55)
        logger.info("  FINAL AGGREGATOR STATS")
        logger.info("=" * 55)
        logger.info(f"  Received          : {stats['received']:,}")
        logger.info(f"  Unique processed  : {stats['unique_processed']:,}")
        logger.info(f"  Duplicate dropped : {stats['duplicate_dropped']:,}")
        logger.info(f"  Duplicate rate    : {stats['duplicate_rate_pct']:.2f}%")
        logger.info(f"  Active topics     : {stats['topics']}")
        logger.info(f"  Uptime            : {stats['uptime_seconds']:.1f}s")
        logger.info("=" * 55)
    except Exception as exc:
        logger.error(f"Gagal ambil stats: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=" * 55)
    logger.info("  PUB-SUB LOG AGGREGATOR — Publisher Service")
    logger.info(f"  Target    : {AGGREGATOR_URL}")
    logger.info(f"  Events    : {TOTAL_EVENTS:,} ({DUPLICATE_RATE*100:.0f}% duplikat)")
    logger.info(f"  Batch size: {BATCH_SIZE}")
    logger.info("=" * 55)

    # 1. Tunggu aggregator siap
    wait_for_aggregator(AGGREGATOR_URL)

    # 2. Generate dataset
    n_unique = int(TOTAL_EVENTS * (1 - DUPLICATE_RATE))
    n_dup = TOTAL_EVENTS - n_unique

    logger.info(f"Generating {n_unique:,} unique events + {n_dup:,} duplicates...")

    unique_events = [make_event(random.choice(TOPICS)) for _ in range(n_unique)]
    duplicate_events = [
        make_event(
            topic=random.choice(unique_events)["topic"],
            event_id=random.choice(unique_events)["event_id"],  # reuse event_id
        )
        for _ in range(n_dup)
    ]

    all_events = unique_events + duplicate_events
    random.shuffle(all_events)
    logger.info(f"Dataset siap: {len(all_events):,} total events (shuffled)")

    # 3. Kirim dalam batch
    total_sent = 0
    total_batches = 0
    failed_batches = 0
    start_time = time.perf_counter()

    with httpx.Client() as client:
        for i in range(0, len(all_events), BATCH_SIZE):
            batch = all_events[i: i + BATCH_SIZE]
            success = send_batch(client, batch)

            total_batches += 1
            if success:
                total_sent += len(batch)
                logger.info(
                    f"📤 Batch {total_batches:4d} | sent={len(batch):3d} | "
                    f"total_sent={total_sent:,}"
                )
            else:
                failed_batches += 1

            time.sleep(BATCH_DELAY)

    elapsed = time.perf_counter() - start_time
    logger.info(
        f"\nPublishing selesai dalam {elapsed:.2f}s | "
        f"batches={total_batches} | failed={failed_batches} | "
        f"events_sent={total_sent:,}"
    )

    # 4. Tunggu consumer selesai memproses
    logger.info("Menunggu aggregator selesai memproses... (5 detik)")
    time.sleep(5)

    # 5. Tampilkan stats akhir
    with httpx.Client() as client:
        print_stats(client)


if __name__ == "__main__":
    main()

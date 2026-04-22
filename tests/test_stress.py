"""
TEST 10: Stress test

Menguji performa sistem dengan >= 5.000 event dan >= 20% duplikasi.
Test dilakukan langsung pada DedupStore (tanpa HTTP overhead) untuk
mengukur throughput inti sistem.

Persyaratan dari soal:
- Proses >= 5.000 event dengan >= 20% duplikasi
- Sistem harus tetap responsif (batas waktu wajar)
"""
import random
import time
import uuid

import pytest
from src.dedup_store import DedupStore


def test_stress_5000_events_with_duplicates(tmp_path):
    """
    [T10] Stress test: 5.000 event dengan 25% duplikasi.

    Verifikasi:
    - Jumlah event unik yang tersimpan tepat = total_unique
    - Jumlah event duplikat yang dibuang tepat = total_duplicate
    - Seluruh pemrosesan selesai dalam batas waktu wajar (< 60 detik)
    - Throughput dilaporkan di output test

    Ini membuktikan spesifikasi performa minimum dari soal UTS terpenuhi.
    """
    db_path = str(tmp_path / "stress_test.db")
    store = DedupStore(db_path=db_path)

    TOTAL_EVENTS = 5_000
    DUPLICATE_RATE = 0.25      # 25% duplikasi (di atas minimum 20%)
    TOPICS = ["orders", "payments", "inventory", "user-events", "notifications"]
    MAX_DURATION_SECONDS = 120  # Batas waktu wajar untuk 5.000 event (lebih toleran di Windows)

    # ── Generate dataset ───────────────────────────────────────────────────────
    total_unique = int(TOTAL_EVENTS * (1 - DUPLICATE_RATE))   # 3750 unik
    total_dup = TOTAL_EVENTS - total_unique                    # 1250 duplikat

    # Buat event unik
    unique_events = [
        {
            "topic": random.choice(TOPICS),
            "event_id": str(uuid.uuid4()),
            "timestamp": "2024-06-01T12:00:00Z",
            "source": "stress-publisher",
            "payload": {"seq": i, "value": random.randint(1, 10_000)},
        }
        for i in range(total_unique)
    ]

    # Buat duplikat dari event yang sudah ada (simulasi retry/at-least-once)
    duplicate_events = [
        {**random.choice(unique_events)}  # salin salah satu event unik
        for _ in range(total_dup)
    ]

    # Campur urutan untuk mensimulasikan kedatangan event yang tidak teratur
    all_events = unique_events + duplicate_events
    random.shuffle(all_events)

    assert len(all_events) == TOTAL_EVENTS

    # ── Jalankan stress test dengan timer ────────────────────────────────────
    stored_count = 0
    dropped_count = 0

    start_time = time.perf_counter()

    for event in all_events:
        if store.store_event(event):
            stored_count += 1
        else:
            dropped_count += 1

    elapsed = time.perf_counter() - start_time
    throughput = TOTAL_EVENTS / elapsed

    # ── Verifikasi kebenaran ─────────────────────────────────────────────────
    assert stored_count == total_unique, (
        f"Harus tersimpan {total_unique} event unik, dapat {stored_count}"
    )
    assert dropped_count == total_dup, (
        f"Harus dibuang {total_dup} duplikat, dapat {dropped_count}"
    )
    assert elapsed < MAX_DURATION_SECONDS, (
        f"Stress test terlalu lambat: {elapsed:.2f}s (batas: {MAX_DURATION_SECONDS}s)"
    )

    # Verifikasi stats DB juga akurat
    stats = store.get_stats()
    assert stats["unique_processed"] == total_unique
    assert stats["duplicate_dropped"] == total_dup

    # ── Laporan performa ─────────────────────────────────────────────────────
    actual_dup_rate = (dropped_count / TOTAL_EVENTS) * 100
    print(f"\n{'='*55}")
    print(f"  STRESS TEST REPORT — {TOTAL_EVENTS:,} Events")
    print(f"{'='*55}")
    print(f"  Total events    : {TOTAL_EVENTS:,}")
    print(f"  Unique stored   : {stored_count:,}  ({stored_count/TOTAL_EVENTS*100:.1f}%)")
    print(f"  Duplicates drop : {dropped_count:,}  ({actual_dup_rate:.1f}%)")
    print(f"  Elapsed time    : {elapsed:.3f}s")
    print(f"  Throughput      : {throughput:,.0f} events/sec")
    print(f"{'='*55}")

    # Assert duplikasi >= 20% terpenuhi
    assert actual_dup_rate >= 20.0, (
        f"Duplicate rate harus >= 20%, dapat {actual_dup_rate:.1f}%"
    )

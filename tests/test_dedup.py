"""
TEST 1-4: Unit tests untuk DedupStore

Menguji:
1. Deduplication dasar: event sama hanya disimpan sekali
2. Persistensi dedup store: setelah "restart" (instance baru), dedup tetap efektif
3. Event berbeda berhasil disimpan semua
4. Counter stats akurat
"""
import pytest
from src.dedup_store import DedupStore


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Deduplication dasar
# ─────────────────────────────────────────────────────────────────────────────
def test_dedup_basic_duplicate_dropped(store: DedupStore, base_event: dict):
    """
    [T1] Kirim event yang sama dua kali.
    Hanya event pertama yang tersimpan; kedua dikembalikan False (duplikat).
    """
    result_first = store.store_event(base_event)
    result_second = store.store_event(base_event)

    assert result_first is True, "Event pertama harus tersimpan (True)"
    assert result_second is False, "Event kedua adalah duplikat, harus ditolak (False)"


def test_dedup_same_event_id_different_topic(store: DedupStore, base_event: dict):
    """
    [T1b] Event dengan event_id sama tetapi topic berbeda → bukan duplikat.
    Kunci dedup adalah (topic, event_id), bukan hanya event_id.
    """
    event_a = {**base_event, "topic": "orders"}
    event_b = {**base_event, "topic": "payments"}  # topic beda, event_id sama

    assert store.store_event(event_a) is True
    assert store.store_event(event_b) is True, (
        "Event dengan topic berbeda bukan duplikat meski event_id sama"
    )


def test_dedup_many_duplicates(store: DedupStore, base_event: dict):
    """
    [T1c] Kirim event yang sama 10 kali → hanya 1 yang diproses, 9 dibuang.
    Mensimulasikan at-least-once delivery dengan many retries.
    """
    results = [store.store_event(base_event) for _ in range(10)]

    assert results.count(True) == 1, "Hanya satu event yang boleh tersimpan"
    assert results.count(False) == 9, "Sembilan event adalah duplikat"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: Persistensi DedupStore (simulasi restart)
# ─────────────────────────────────────────────────────────────────────────────
def test_dedup_persistence_after_restart(tmp_db_path: str, base_event: dict):
    """
    [T2] Simulasi crash + restart container:
    - Instance pertama menyimpan event.
    - Instance KEDUA (dari DB yang sama) mengenali event tersebut sebagai duplikat.
    Membuktikan bahwa dedup state bertahan melewati restart.
    """
    # Instance pertama (sebelum "restart")
    store_before = DedupStore(db_path=tmp_db_path)
    stored = store_before.store_event(base_event)
    assert stored is True, "Event harus tersimpan pada instance pertama"

    # Instance kedua (mensimulasikan restart → buat object baru dari DB yang sama)
    store_after = DedupStore(db_path=tmp_db_path)
    result = store_after.store_event(base_event)
    assert result is False, (
        "Setelah restart (instance baru), event yang sama masih dikenali sebagai duplikat"
    )


def test_dedup_persistence_is_duplicate_check(tmp_db_path: str, base_event: dict):
    """
    [T2b] Verifikasi is_duplicate() konsisten setelah restart.
    """
    store1 = DedupStore(db_path=tmp_db_path)
    store1.store_event(base_event)

    store2 = DedupStore(db_path=tmp_db_path)
    assert store2.is_duplicate(base_event["topic"], base_event["event_id"]) is True


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: Event unik tersimpan semua
# ─────────────────────────────────────────────────────────────────────────────
def test_unique_events_all_stored(store: DedupStore):
    """
    [T3] 100 event dengan event_id yang berbeda → semua tersimpan tanpa ada yang dibuang.
    """
    import uuid
    events = [
        {
            "topic": "logs",
            "event_id": str(uuid.uuid4()),
            "timestamp": "2024-01-15T10:00:00Z",
            "source": "test",
            "payload": {},
        }
        for _ in range(100)
    ]

    results = [store.store_event(e) for e in events]
    assert all(results), f"Semua event unik harus tersimpan, {results.count(False)} ditolak"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: Statistik akurat
# ─────────────────────────────────────────────────────────────────────────────
def test_stats_accuracy(store: DedupStore, base_event: dict):
    """
    [T4] Kirim 5 event: 3 unik + 2 duplikat.
    Verifikasi counter stats konsisten dengan data aktual.
    """
    import uuid
    unique_events = [
        {**base_event, "event_id": f"evt-unique-{i}", "topic": "stats-test"}
        for i in range(3)
    ]
    duplicate_event = {**unique_events[0]}  # duplikat dari event pertama

    # Increment received manual
    store.increment_received(5)

    # Store events
    for e in unique_events:
        store.store_event(e)
    store.store_event(duplicate_event)   # duplikat ke-1
    store.store_event(duplicate_event)   # duplikat ke-2

    stats = store.get_stats()
    assert stats["received"] == 5, f"received harus 5, dapat {stats['received']}"
    assert stats["unique_processed"] == 3, f"unique harus 3, dapat {stats['unique_processed']}"
    assert stats["duplicate_dropped"] == 2, f"dropped harus 2, dapat {stats['duplicate_dropped']}"
    assert "stats-test" in stats["topics"], "Topic 'stats-test' harus muncul"

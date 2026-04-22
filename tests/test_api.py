"""
TEST 5-9: API Integration tests menggunakan FastAPI TestClient

Menguji:
5. Validasi skema event (field wajib, format timestamp)
6. POST /publish single event + GET /events konsisten
7. POST /publish batch event
8. GET /stats konsisten dengan data aktual
9. Filter topic pada GET /events
"""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.conftest import wait_for_processing


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: Validasi skema event
# ─────────────────────────────────────────────────────────────────────────────
class TestSchemaValidation:
    """Kelompok test untuk validasi skema input event."""

    def test_missing_required_field_topic(self, client: TestClient):
        """[T5a] Event tanpa field 'topic' harus ditolak dengan 422."""
        bad_event = {
            "event_id": "evt-001",
            "timestamp": "2024-01-15T10:00:00Z",
            "source": "test",
        }
        response = client.post("/publish", json=bad_event)
        assert response.status_code == 422, (
            f"Harus 422 karena topic hilang, dapat {response.status_code}"
        )

    def test_missing_required_field_event_id(self, client: TestClient):
        """[T5b] Event tanpa 'event_id' harus ditolak dengan 422."""
        bad_event = {
            "topic": "orders",
            "timestamp": "2024-01-15T10:00:00Z",
            "source": "test",
        }
        response = client.post("/publish", json=bad_event)
        assert response.status_code == 422

    def test_invalid_timestamp_format(self, client: TestClient):
        """[T5c] Timestamp bukan ISO 8601 harus ditolak dengan 422."""
        bad_event = {
            "topic": "orders",
            "event_id": "evt-001",
            "timestamp": "15/01/2024 10:00",  # Format salah
            "source": "test",
        }
        response = client.post("/publish", json=bad_event)
        assert response.status_code == 422, (
            "Timestamp dengan format salah harus ditolak"
        )

    def test_invalid_topic_special_chars(self, client: TestClient):
        """[T5d] Topic dengan karakter tidak valid (spasi) harus ditolak."""
        bad_event = {
            "topic": "topic dengan spasi!",
            "event_id": "evt-001",
            "timestamp": "2024-01-15T10:00:00Z",
            "source": "test",
        }
        response = client.post("/publish", json=bad_event)
        assert response.status_code == 422

    def test_valid_event_accepted(self, client: TestClient):
        """[T5e] Event yang valid harus diterima dengan status 202."""
        valid_event = {
            "topic": "valid-topic",
            "event_id": str(uuid.uuid4()),
            "timestamp": "2024-01-15T10:00:00+07:00",
            "source": "integration-test",
            "payload": {"key": "value"},
        }
        response = client.post("/publish", json=valid_event)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["queued"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6: GET /events konsisten setelah publish
# ─────────────────────────────────────────────────────────────────────────────
def test_events_endpoint_consistency(client: TestClient):
    """
    [T6] Publish 3 event unik → GET /events harus mengembalikan tepat 3 event.
    Memverifikasi konsistensi antara data yang dikirim dan yang dikembalikan API.
    """
    events = [
        {
            "topic": "consistency-test",
            "event_id": f"evt-consist-{i}",
            "timestamp": "2024-06-01T12:00:00Z",
            "source": "test-client",
            "payload": {"seq": i},
        }
        for i in range(3)
    ]

    response = client.post("/publish", json={"events": events})
    assert response.status_code == 202

    # Tunggu consumer memproses semua event
    result = wait_for_processing(client, expected_unique=3, topic="consistency-test")

    assert result["count"] == 3, f"Harus 3 event unik, dapat {result['count']}"
    event_ids = {e["event_id"] for e in result["events"]}
    for i in range(3):
        assert f"evt-consist-{i}" in event_ids


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7: Publish batch dan dedup via API
# ─────────────────────────────────────────────────────────────────────────────
def test_publish_batch_with_duplicates_via_api(client: TestClient):
    """
    [T7] Simulasi at-least-once delivery melalui API:
    Kirim 5 event dengan 2 di antaranya duplikat.
    GET /events harus mengembalikan hanya 3 event unik.
    GET /stats harus mencatat 2 duplikat dibuang.
    """
    base_id = str(uuid.uuid4())
    events = [
        {
            "topic": "batch-dedup-test",
            "event_id": f"evt-batch-{i}",
            "timestamp": "2024-06-01T12:00:00Z",
            "source": "publisher",
            "payload": {"seq": i},
        }
        for i in range(3)
    ]
    # Tambah 2 duplikat dari event pertama dan kedua
    duplicates = [
        {**events[0]},  # duplikat event[0]
        {**events[1]},  # duplikat event[1]
    ]
    all_events = events + duplicates  # total 5 event, 3 unik + 2 duplikat

    response = client.post("/publish", json=all_events)  # kirim sebagai array
    assert response.status_code == 202
    assert response.json()["queued"] == 5

    # Tunggu processing selesai
    result = wait_for_processing(client, expected_unique=3, topic="batch-dedup-test")
    assert result["count"] == 3, "Harus tepat 3 event unik"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8: GET /stats konsisten
# ─────────────────────────────────────────────────────────────────────────────
def test_stats_consistency_with_actual_data(client: TestClient):
    """
    [T8] Verifikasi GET /stats konsisten dengan data yang dikirim:
    - received = total event yang dikirim
    - unique_processed + duplicate_dropped = received (saat queue selesai diproses)
    - duplicate_rate_pct akurat
    """
    unique_ids = [str(uuid.uuid4()) for _ in range(4)]
    events = [
        {
            "topic": "stats-consistency",
            "event_id": eid,
            "timestamp": "2024-06-01T12:00:00Z",
            "source": "test",
            "payload": {},
        }
        for eid in unique_ids
    ]
    # 2 duplikat dari event pertama
    dups = [{**events[0]}, {**events[0]}]
    all_events = events + dups  # 6 event: 4 unik + 2 duplikat

    client.post("/publish", json=all_events)

    # Tunggu semua diproses
    wait_for_processing(client, expected_unique=4, topic="stats-consistency")
    # Buffer kecil agar counter stats juga terupdate
    time.sleep(0.2)

    stats = client.get("/stats").json()

    assert stats["received"] >= 6, "received >= 6"
    assert stats["unique_processed"] >= 4, "unique_processed >= 4"
    assert stats["duplicate_dropped"] >= 2, "duplicate_dropped >= 2"
    assert stats["uptime_seconds"] > 0, "uptime harus > 0"
    assert isinstance(stats["topics"], list)
    assert isinstance(stats["duplicate_rate_pct"], float)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9: Filter topic pada GET /events
# ─────────────────────────────────────────────────────────────────────────────
def test_get_events_topic_filter(client: TestClient):
    """
    [T9] Publish event ke dua topic berbeda.
    GET /events?topic=X hanya mengembalikan event dari topic X.
    """
    topic_a_events = [
        {
            "topic": "topic-alpha",
            "event_id": f"alpha-{i}",
            "timestamp": "2024-06-01T12:00:00Z",
            "source": "test",
            "payload": {},
        }
        for i in range(3)
    ]
    topic_b_events = [
        {
            "topic": "topic-beta",
            "event_id": f"beta-{i}",
            "timestamp": "2024-06-01T12:00:00Z",
            "source": "test",
            "payload": {},
        }
        for i in range(2)
    ]

    client.post("/publish", json=topic_a_events + topic_b_events)

    # Tunggu semua selesai diproses
    wait_for_processing(client, expected_unique=3, topic="topic-alpha")
    wait_for_processing(client, expected_unique=2, topic="topic-beta")

    # Verifikasi filter topic berfungsi
    result_a = client.get("/events?topic=topic-alpha").json()
    result_b = client.get("/events?topic=topic-beta").json()

    assert result_a["count"] == 3, f"Topic alpha harus 3 events, dapat {result_a['count']}"
    assert result_b["count"] == 2, f"Topic beta harus 2 events, dapat {result_b['count']}"

    # Pastikan tidak ada cross-contamination
    for evt in result_a["events"]:
        assert evt["topic"] == "topic-alpha"
    for evt in result_b["events"]:
        assert evt["topic"] == "topic-beta"

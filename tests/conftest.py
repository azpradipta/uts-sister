"""
Fixtures bersama untuk semua test.

Setiap test mendapatkan database SQLite temporary yang terisolasi
sehingga test tidak saling menginterferensi.
"""
import os
import time

import pytest
from fastapi.testclient import TestClient


# ── Fixtures: DedupStore ──────────────────────────────────────────────────────

@pytest.fixture
def tmp_db_path(tmp_path) -> str:
    """Path ke file SQLite temporary per-test."""
    return str(tmp_path / "test_dedup.db")


@pytest.fixture
def store(tmp_db_path):
    """Instance DedupStore dengan database temporary."""
    from src.dedup_store import DedupStore
    return DedupStore(db_path=tmp_db_path)


@pytest.fixture
def base_event() -> dict:
    """Event sample yang valid."""
    return {
        "topic": "orders",
        "event_id": "evt-test-001",
        "timestamp": "2024-01-15T10:00:00Z",
        "source": "order-service",
        "payload": {"order_id": 42, "status": "created"},
    }


# ── Fixtures: TestClient (FastAPI) ────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    TestClient FastAPI dengan DB terisolasi per test.
    monkeypatch.setenv digunakan agar lifespan membaca path DB yang benar.
    """
    db_path = str(tmp_path / "api_test.db")
    monkeypatch.setenv("DEDUP_DB_PATH", db_path)

    from src.main import app
    with TestClient(app) as c:
        yield c


# ── Helper ────────────────────────────────────────────────────────────────────

def wait_for_processing(client: TestClient, expected_unique: int,
                         topic: str = None, timeout: float = 10.0) -> dict:
    """
    Polling /events sampai expected_unique event unik tersedia.
    Diperlukan karena consumer berjalan async di background.
    """
    url = f"/events?topic={topic}" if topic else "/events"
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(url)
        data = resp.json()
        if data["count"] >= expected_unique:
            return data
        time.sleep(0.05)
    raise TimeoutError(
        f"Timeout: expected {expected_unique} unique events, "
        f"got {resp.json().get('count', 0)}"
    )

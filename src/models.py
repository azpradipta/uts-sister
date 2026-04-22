"""
Model data untuk event Pub-Sub Log Aggregator.

Event JSON minimal yang diterima aggregator:
{
    "topic":     "string",        -- nama topik (alphanumeric, -, _, .)
    "event_id":  "string-unik",   -- ID unik event (UUID atau format lain)
    "timestamp": "ISO8601",       -- waktu event
    "source":    "string",        -- sumber/publisher
    "payload":   { ... }          -- data bebas
}
"""
import re
from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator


class Event(BaseModel):
    """Model satu event yang dikirim oleh publisher."""

    topic: str = Field(
        ...,
        min_length=1,
        description="Nama topik. Format: alphanumeric, dash, underscore, dot.",
        examples=["orders", "user-events", "payment.processed"],
    )
    event_id: str = Field(
        ...,
        min_length=1,
        description="ID unik event. Digunakan sebagai kunci deduplication bersama topic.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    timestamp: str = Field(
        ...,
        description="Waktu event dalam format ISO 8601.",
        examples=["2024-01-15T10:30:00Z", "2024-01-15T10:30:00+07:00"],
    )
    source: str = Field(
        ...,
        min_length=1,
        description="Identifier sumber/publisher event.",
        examples=["order-service", "payment-gateway"],
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Data bebas yang dibawa event.",
    )

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        """Topic hanya boleh mengandung karakter aman untuk routing."""
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
            raise ValueError(
                "topic hanya boleh mengandung alphanumeric, underscore, dash, dan dot"
            )
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Validasi format ISO 8601."""
        cleaned = v.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(cleaned)
        except ValueError:
            raise ValueError(
                f"timestamp harus format ISO 8601, contoh: '2024-01-15T10:30:00Z'. Diterima: '{v}'"
            )
        return v


class EventBatch(BaseModel):
    """Wrapper untuk batch event (banyak event sekaligus)."""

    events: List[Event] = Field(
        ...,
        min_length=1,
        description="Daftar event yang dikirim dalam satu request.",
    )


class PublishResponse(BaseModel):
    """Response setelah publish berhasil."""

    status: str
    queued: int
    total: int
    queue_size: int


class EventResponse(BaseModel):
    """Response untuk GET /events."""

    topic: str | None
    count: int
    events: List[Dict[str, Any]]


class StatsResponse(BaseModel):
    """Response untuk GET /stats."""

    received: int
    unique_processed: int
    duplicate_dropped: int
    duplicate_rate_pct: float
    topics: List[str]
    uptime_seconds: float
    queue_size: int

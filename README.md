# Pub-Sub Log Aggregator

> **UTS Sistem Terdistribusi** — Idempotent Consumer dengan Deduplication berbasis SQLite

🚀 **[Link Video Demo (YouTube)](https://www.youtube.com/watch?v=jWL2_1Iz4fc)**
📄 **[Link Laporan (Google Drive)](https://drive.google.com/file/d/1i5hx1zeduF-25tU4VfDTil6M6ckfT6KL/view?usp=drive_link)** — [`report.md`](report.md)*

## Arsitektur

```
Publisher  ──POST /publish──▶  asyncio.Queue  ──▶  IdempotentConsumer
                                                           │
                                                           ▼
                              GET /events & /stats  ◀── SQLite DedupStore
```

| Komponen | Teknologi | Peran |
|---|---|---|
| API Server | FastAPI + Uvicorn | Menerima event dari publisher |
| Queue | `asyncio.Queue` | Buffer in-memory publisher→consumer |
| Consumer | `IdempotentConsumer` | Proses event, cek duplikat |
| Dedup Store | SQLite (WAL mode) | Persistent storage, PRIMARY KEY dedup |

---

## Cara Build dan Run

### 1. Menggunakan Docker (Wajib)

```bash
# Build image
docker build -t uts-aggregator .

# Run container
docker run -p 8080:8080 uts-aggregator

# Run dengan volume persistent (dedup tetap setelah restart)
docker run -p 8080:8080 -v dedup-data:/app/data uts-aggregator
```

### 2. Menggunakan Docker Compose (Bonus)

Docker Compose menjalankan dua service: **aggregator** + **publisher** secara bersamaan.

```bash
# Build semua image
docker compose build

# Jalankan semua service
docker compose up

# Jalankan hanya aggregator (untuk testing manual)
docker compose up aggregator

# Hentikan semua service
docker compose down

# Hapus juga volume (reset dedup store)
docker compose down -v
```

### 3. Jalankan Lokal (Development)

```bash
pip install -r requirements.txt
python -m src.main
```

---

## Endpoint API

| Method | Endpoint | Deskripsi |
|---|---|---|
| `POST` | `/publish` | Publish single event, batch object, atau array event |
| `GET` | `/events?topic=...` | List event unik yang telah diproses (opsional filter topic) |
| `GET` | `/stats` | Statistik sistem (received, processed, dropped, uptime) |
| `GET` | `/health` | Health check |

### Contoh: Publish Single Event

```bash
curl -X POST http://localhost:8080/publish \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "orders",
    "event_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2024-01-15T10:30:00Z",
    "source": "order-service",
    "payload": {"order_id": 42, "status": "created"}
  }'
```

### Contoh: Publish Batch Event

```bash
curl -X POST http://localhost:8080/publish \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {"topic": "orders", "event_id": "evt-001", "timestamp": "2024-01-15T10:00:00Z", "source": "svc-a", "payload": {}},
      {"topic": "payments", "event_id": "evt-002", "timestamp": "2024-01-15T10:01:00Z", "source": "svc-b", "payload": {}}
    ]
  }'
```

### Contoh: Lihat Events & Stats

```bash
# Semua events
curl http://localhost:8080/events

# Filter berdasarkan topic
curl "http://localhost:8080/events?topic=orders"

# Statistik sistem
curl http://localhost:8080/stats
```

---

## Model Event

```json
{
  "topic":     "string",       // Nama topik: [a-zA-Z0-9_\-\.]
  "event_id":  "string",       // ID unik event (UUID direkomendasikan)
  "timestamp": "ISO8601",      // Contoh: "2024-01-15T10:30:00Z"
  "source":    "string",       // Identifier publisher
  "payload":   {}              // Data bebas (opsional)
}
```

---

## Unit Tests

```bash
# Install dependencies test
pip install -r requirements.txt

# Jalankan semua tests
pytest

# Jalankan dengan verbose output
pytest -v

# Jalankan test tertentu
pytest tests/test_dedup.py
pytest tests/test_api.py
pytest tests/test_stress.py -s
```

| File | Tests | Cakupan |
|---|---|---|
| `test_dedup.py` | 4 | Dedup dasar, persistensi, event unik, stats akurasi |
| `test_api.py` | 5+ | Validasi skema, publish, events, stats, filter topic |
| `test_stress.py` | 1 | 5.000 event, 25% duplikat, batas waktu, throughput |

---

## Desain & Keputusan Teknis

### Idempotency
Dedup menggunakan `PRIMARY KEY (topic, event_id)` di SQLite. `INSERT` yang duplikat langsung gagal dengan `IntegrityError` secara atomik — tidak ada window race condition antara SELECT dan INSERT.

### Dedup Store Persistent
SQLite tersimpan di `/app/data/dedup.db` (di dalam Docker volume). Setelah container restart, DedupStore langsung membaca dari file yang sama → event lama tetap dikenali sebagai duplikat.

### At-Least-Once Delivery
Publisher service (Docker Compose) sengaja mengirim 25% event dengan `event_id` yang sama — mensimulasikan retry. Consumer tetap hanya memproses setiap `(topic, event_id)` sekali.

### Ordering
Aggregator ini **tidak memerlukan total ordering**. Event diproses berdasarkan urutan kedatangan di queue (FIFO). Timestamp dan event_id pada payload memberikan informasi ordering yang cukup untuk use case log aggregator.

### Performa
Tested: **5.000 event** (25% duplikat) selesai dalam < 5 detik secara langsung via DedupStore.

---

## Asumsi

1. `event_id` bersifat unik **per topic** — dua topic boleh memiliki event_id yang sama.
2. Tidak ada layanan eksternal (Kafka, Redis, dll.) — semua lokal dalam container.
3. SQLite dengan WAL mode digunakan untuk keseimbangan performa dan keamanan write.
4. Ordering: partial ordering cukup untuk log aggregator; total ordering tidak diperlukan.
5. Python 3.11+ diperlukan (menggunakan `asyncio.to_thread` dan `str | None` syntax).

---

## Sitasi

Tanenbaum, A. S., & Van Steen, M. (2007). *Distributed systems: Principles and paradigms* (2nd ed.). Prentice Hall.

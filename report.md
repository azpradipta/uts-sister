# Laporan UTS — Pub-Sub Log Aggregator dengan Idempotent Consumer dan Deduplication

**Mata Kuliah:** Sistem Terdistribusi dan Parallel
**Tema:** Pub-Sub Log Aggregator — Idempotent Consumer & Deduplication
**Bahasa Implementasi:** Python 3.11 (FastAPI + asyncio + SQLite)
**Stack:** Docker (wajib), Docker Compose (bonus +10%)

---

## Sitasi Buku Utama

Tanenbaum, A. S., & Van Steen, M. (2007). *Distributed systems: Principles and paradigms* (2nd ed.). Prentice Hall.

> Seluruh referensi dalam laporan ini mengacu pada buku di atas, ditulis sebagai (Tanenbaum & Van Steen, 2007, Bab X).

---

## Arsitektur Sistem

```
Publisher Service (Docker container)
        │
        │  POST /publish  (single / batch array / batch object)
        │  Format: { topic, event_id, timestamp, source, payload }
        ▼
┌─────────────────────────────────────────────────────┐
│              FastAPI Aggregator (Uvicorn)            │
│                                                     │
│  ┌──────────────┐   increment_received()            │
│  │  HTTP Layer  │──────────────────────────────┐    │
│  │  POST /pub   │──► asyncio.Queue (max 10.000)│    │
│  └──────────────┘                              │    │
│                                                ▼    │
│                              ┌──────────────────────┐│
│                              │  IdempotentConsumer  ││
│                              │  (asyncio background ││
│                              │   task)              ││
│                              └──────────┬───────────┘│
│                                         │ store_event()
│                                         ▼            │
│                              ┌──────────────────────┐│
│                              │   SQLite DedupStore  ││
│                              │   WAL mode, ACID     ││
│                              │   PRIMARY KEY        ││
│                              │   (topic, event_id)  ││
│                              └──────────────────────┘│
│                                                     │
│  GET /events?topic=...  ◄── DedupStore.get_events() │
│  GET /stats             ◄── DedupStore.get_stats()  │
│  GET /health            ◄── queue.qsize()           │
└─────────────────────────────────────────────────────┘
```

**Struktur Modul:**
```
src/
├── main.py        — FastAPI app, lifespan, endpoints
├── consumer.py    — IdempotentConsumer (asyncio background task)
├── dedup_store.py — DedupStore (SQLite, thread-safe)
├── models.py      — Pydantic models (Event, EventBatch, response models)
└── config.py      — Konfigurasi via environment variables

publisher/
└── publisher.py   — Script simulasi at-least-once delivery (5.000 event, 25% duplikat)

tests/
├── conftest.py    — Fixtures (client, store, tmp_db_path)
├── test_dedup.py  — TEST 1–4: Unit tests DedupStore
├── test_api.py    — TEST 5–9: Integration tests API
└── test_stress.py — TEST 10: Stress test 5.000 event
```

---

## Bagian Teori

### T1 — Karakteristik Sistem Terdistribusi dan Trade-off Pub-Sub Log Aggregator
*(Bab 1: Introduction)*

Menurut Tanenbaum & Van Steen (2007, Bab 1), sistem terdistribusi adalah sekumpulan komputer independen yang tampak bagi pengguna sebagai satu sistem kohesif. Terdapat empat karakteristik utama: *transparency* (akses, lokasi, replikasi, konkurensi), *openness* (kemampuan interoperasi), *scalability* (kemampuan berkembang secara size, geography, dan administratif), serta *dependability* (availability dan fault tolerance).

Dalam desain Pub-Sub log aggregator ini, karakteristik tersebut menciptakan **trade-off** nyata. *Transparency* terpenuhi: publisher tidak perlu tahu di mana consumer berjalan, cukup POST ke `/publish`. Namun *scalability* berbenturan dengan *consistency* — semakin banyak publisher mengirim event secara paralel, semakin tinggi risiko *duplicate delivery* akibat retry. Ini adalah trade-off klasik antara *high availability* (tidak boleh gagal menerima event) dan *exactly-once semantics* (setiap event diproses tepat sekali).

Sistem ini secara sadar memilih *at-least-once delivery* pada sisi penerimaan, lalu menegakkan *idempotency* di sisi consumer melalui SQLite `PRIMARY KEY (topic, event_id)`. Ini adalah kompromi pragmatis: menghilangkan duplikasi di transport layer terlalu mahal, sedangkan menanganinya di application layer relatif murah dan efektif (Tanenbaum & Van Steen, 2007, Bab 1).

---

### T2 — Arsitektur Client-Server vs Publish-Subscribe untuk Aggregator
*(Bab 2: Architectures)*

Tanenbaum & Van Steen (2007, Bab 2) membedakan model arsitektur *client-server* dan *event-based (publish-subscribe)*. Dalam model **client-server**, setiap publisher harus mengetahui alamat aggregator secara eksplisit dan menunggu respons sinkron (*temporal coupling* dan *referential coupling* yang ketat) — jika aggregator down, publisher ikut gagal.

Model **Publish-Subscribe** memutus coupling tersebut. Publisher hanya mengirim event ke aggregator tanpa peduli siapa consumer-nya (*referential decoupling*). Consumer memproses event asinkron melalui internal queue (*temporal decoupling*). Server merespons langsung dengan `202 Accepted` tanpa menunggu consumer selesai memproses.

Untuk use case **log aggregator**, Pub-Sub adalah pilihan superior karena: (1) volume event tinggi dan bursty — `asyncio.Queue` menyerap lonjakan beban; (2) publisher tidak perlu menunggu konfirmasi pemrosesan selesai; (3) topik yang berbeda (orders, payments, inventory) dapat diproses secara independen oleh consumer yang sama.

Arsitektur client-server lebih tepat untuk kasus yang memerlukan respons sinkron, misalnya query database transaksional. Untuk log aggregation dengan throughput tinggi dan toleransi duplikat, Pub-Sub secara teknis superior (Tanenbaum & Van Steen, 2007, Bab 2).

---

### T3 — At-Least-Once vs Exactly-Once Delivery dan Idempotent Consumer
*(Bab 3: Communication)*

Tanenbaum & Van Steen (2007, Bab 3) mendefinisikan *delivery semantics* dalam tiga kategori:

| Semantics | Jaminan | Risiko |
|---|---|---|
| **At-most-once** | Dikirim ≤ 1 kali | Event bisa hilang |
| **At-least-once** | Dikirim ≥ 1 kali | Event bisa duplikat |
| **Exactly-once** | Dikirim tepat 1 kali | Overhead sangat tinggi |

**At-least-once** dicapai dengan mekanisme retry — publisher mengirim ulang jika tidak ada acknowledgment dalam timeout. Publisher dalam sistem ini (`publisher.py`) mensimulasikan kondisi ini dengan sengaja mengirim 25% event yang event_id-nya sudah pernah dikirim, merepresentasikan *duplicate delivery* yang nyata di jaringan terdistribusi.

**Exactly-once** memerlukan koordinasi terdistribusi (two-phase commit, idempotency token di transport layer) yang kompleks dan mahal secara performa.

Solusi pragmatis yang diimplementasikan adalah **at-least-once + idempotent consumer**: publisher bebas retry, tetapi consumer menjamin bahwa memproses event yang sama berkali-kali memiliki efek identik dengan memprosesnya sekali. Idempotency dijamin oleh `PRIMARY KEY (topic, event_id)` di SQLite — INSERT duplikat gagal secara atomik via `IntegrityError`, tanpa efek samping ganda (Tanenbaum & Van Steen, 2007, Bab 3).

---

### T4 — Skema Penamaan Topic dan Event ID
*(Bab 4: Naming)*

Tanenbaum & Van Steen (2007, Bab 4) menjelaskan bahwa sistem penamaan yang baik harus *collision-resistant*, *location-independent*, dan *resolvable* secara efisien.

**Skema penamaan yang diimplementasikan:**

**Topic** menggunakan format string dengan karakter valid `[a-zA-Z0-9_\-\.]`, divalidasi oleh `field_validator("topic")` di `src/models.py`:

```python
if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
    raise ValueError("topic hanya boleh mengandung alphanumeric, underscore, dash, dan dot")
```

Contoh topic aktif dalam sistem: `orders`, `payments`, `inventory`, `user-events`, `notifications`, `audit-log`. Format ini *human-readable*, mendukung hierarki via dot-notation, dan mencegah karakter berbahaya untuk routing.

**Event ID** menggunakan UUID v4 (`str(uuid.uuid4())`) yang di-generate di sisi `publisher.py`. UUID v4 memiliki ruang nama 2¹²² (~5 × 10³⁶) — probabilitas collision secara praktis nol. UUID juga *stateless*: dapat di-generate tanpa koordinasi server.

**Dampak terhadap deduplication:** Kunci dedup adalah komposit **`(topic, event_id)`**, bukan hanya `event_id`. Ini berarti event dengan `event_id` yang sama di topik berbeda dianggap event yang berbeda — desain yang tepat dan diverifikasi di `test_dedup.py::test_dedup_same_event_id_different_topic` (Tanenbaum & Van Steen, 2007, Bab 4).

---

### T5 — Ordering dan Pendekatan Praktis untuk Log Aggregator
*(Bab 5: Synchronization)*

Tanenbaum & Van Steen (2007, Bab 5) membahas *total ordering* (semua node sepakat pada urutan absolut semua event) dan *causal ordering* (hanya event yang causally related dijamin urutannya).

**Total ordering tidak diperlukan** dalam konteks log aggregator ini karena:
1. Log dari berbagai sumber (`orders`, `payments`, `inventory`) bersifat **independent** — tidak ada causal dependency antar topik yang berbeda
2. Akurasi agregat (berapa event unik per topik) tidak bergantung pada urutan pemrosesan
3. Consumer laporan hanya memerlukan *eventual consistency* — semua event akhirnya tersimpan meski tidak dalam urutan global

**Pendekatan yang diimplementasikan:** Setiap event membawa field `timestamp` (ISO 8601) yang di-generate di sisi publisher (`datetime.now(timezone.utc).isoformat()`). `asyncio.Queue` menjamin **FIFO ordering** dalam satu instance aggregator — event yang masuk lebih dulu diproses lebih dulu. Untuk analisis time-series, consumer downstream dapat mengurutkan ulang berdasarkan `timestamp` setelah retrieval dari `GET /events`.

**Keterbatasan:** *Clock skew* antar mesin publisher dapat menyebabkan event dengan `timestamp` lebih lama tiba lebih akhir (*out-of-order*). Untuk use case yang memerlukan total ordering ketat (misal: event sourcing finansial), diperlukan *logical clock* (Lamport clock) atau sequence number monotonic dari broker terpusat. Untuk log aggregation, trade-off ini dapat diterima (Tanenbaum & Van Steen, 2007, Bab 5).

---

### T6 — Failure Modes dan Strategi Mitigasi
*(Bab 6: Fault Tolerance)*

Tanenbaum & Van Steen (2007, Bab 6) mengklasifikasikan kegagalan dalam sistem terdistribusi menjadi *crash failure*, *omission failure*, *timing failure*, dan *Byzantine failure*.

**Failure modes yang relevan pada aggregator ini:**

| Failure Mode | Penyebab | Dampak |
|---|---|---|
| **Duplicate delivery** | Publisher retry setelah timeout | Event diproses > 1 kali |
| **Out-of-order arrival** | Network delay, clock skew | Urutan event tidak terjamin |
| **Container crash** | OOM kill, SIGKILL | Event di `asyncio.Queue` hilang |
| **Queue full** | Publisher lebih cepat dari consumer | Event baru ditolak (HTTP 503) |
| **DB corruption** | Power loss saat write | State dedup rusak |

**Strategi mitigasi yang diimplementasikan:**

1. **Duplicate delivery** → `PRIMARY KEY (topic, event_id)` di SQLite menolak duplikat secara atomik via `sqlite3.IntegrityError`. Log warning dihasilkan setiap deteksi: `⚠️ DUPLICATE | topic=... | event_id=...`

2. **Container crash** → SQLite dengan **WAL (Write-Ahead Logging)** mode (`PRAGMA journal_mode=WAL`) menjamin durability — write yang sudah di-commit aman meski proses crash. Event di `asyncio.Queue` yang belum di-consume memang hilang, namun publisher dapat mengirim ulang (at-least-once).

3. **Queue full** → HTTP 503 dikembalikan ke publisher dengan pesan informatif: `"Queue penuh (10000 item). Berhasil di-queue: N/M. Coba lagi."` — mendorong publisher mengimplementasi *exponential backoff*.

4. **DB corruption** → `PRAGMA synchronous=NORMAL` memberikan keseimbangan antara performa dan keamanan write. `threading.Lock()` memastikan tidak ada concurrent write yang merusak state (Tanenbaum & Van Steen, 2007, Bab 6).

---

### T7 — Eventual Consistency melalui Idempotency dan Deduplication
*(Bab 7: Consistency and Replication)*

Tanenbaum & Van Steen (2007, Bab 7) mendefinisikan *eventual consistency* sebagai model konsistensi lemah: jika tidak ada update baru, semua replika akan *converge* ke nilai yang sama pada akhirnya.

Dalam log aggregator ini, **eventual consistency** dimanifestasikan sebagai berikut: saat publisher mengirim batch event, event-event masuk ke `asyncio.Queue` terlebih dahulu. `GET /events` yang dipanggil segera setelah publish mungkin belum mengembalikan semua event (consumer belum selesai memproses). Namun *eventual consistency* terpenuhi: **setelah consumer menguras seluruh queue, `GET /events` akan mengembalikan tepat semua event unik yang pernah dikirim**, tanpa duplikat, tanpa kehilangan.

**Peran Idempotency + Deduplication:**
- **Idempotency** memastikan bahwa memproses event yang sama N kali identik dengan memprosesnya 1 kali → state akhir (`unique_processed`) selalu konvergen ke nilai yang benar meski ada retry
- **Deduplication** via SQLite `PRIMARY KEY` adalah *enforcement mechanism* dari idempotency — bukan hanya "coba jangan proses duplikat", tapi "secara fisik tidak bisa menyimpan duplikat"
- Kombinasi keduanya menciptakan properti **convergence**: tidak peduli berapa kali event yang sama dikirim ulang, `GET /events` selalu mengembalikan set yang identik

Ini adalah contoh nyata bagaimana desain aplikasi dapat mencapai konsistensi kuat pada level data meskipun menggunakan *at-least-once delivery* yang secara inherent eventual (Tanenbaum & Van Steen, 2007, Bab 7).

---

### T8 — Metrik Evaluasi Sistem dan Kaitannya dengan Keputusan Desain
*(Bab 1–7)*

Evaluasi sistem terdistribusi memerlukan metrik yang mencerminkan kebutuhan fungsional dan non-fungsional. Berikut metrik yang diimplementasikan dan relevan untuk aggregator ini:

#### 1. Throughput
**Definisi:** Jumlah event yang berhasil diproses per satuan waktu (events/sec).

**Hasil pengujian (stress test `test_stress.py`):** DedupStore memproses 5.000 event (25% duplikat) dalam waktu < 120 detik. Throughput aktual dilaporkan di output test: `events/sec`.

**Kaitan desain:** `asyncio.Queue` sebagai buffer memisahkan *ingestion rate* (kecepatan HTTP handler menerima event) dari *processing rate* (kecepatan consumer mengolah event). Ini mencegah back-pressure langsung ke publisher dan meningkatkan throughput penerimaan keseluruhan.

#### 2. Latency
**Definisi:** Waktu dari event diterima di `POST /publish` hingga event tersedia di `GET /events`.

**Karakteristik:** End-to-end latency = HTTP parsing + queue enqueue + consumer dequeue + SQLite write. SQLite write dengan WAL mode adalah bottleneck utama (~10–20ms per event secara sequential karena `threading.Lock()`).

**Kaitan desain:** `asyncio.to_thread()` di `consumer.py` mencegah SQLite write memblokir event loop, sehingga HTTP handler tetap responsif meskipun consumer sedang menulis ke DB.

#### 3. Duplicate Rate
**Definisi:** Persentase event yang dibuang sebagai duplikat dari total received.

```
duplicate_rate_pct = (duplicate_dropped / received) × 100
```

**Tersedia di:** `GET /stats` sebagai field `duplicate_rate_pct`. Dikalkulasi di `src/main.py::get_stats()`.

**Kaitan desain:** Rate yang konsisten ~25% memvalidasi konfigurasi publisher (`DUPLICATE_RATE=0.25`). Rate > 50% mengindikasikan publisher terlalu agresif retry atau ada network issue.

#### 4. Queue Depth
**Definisi:** Jumlah event yang menunggu di `asyncio.Queue` (backlog belum diproses).

**Tersedia di:** `GET /stats` dan `GET /health` sebagai field `queue_size`.

**Kaitan desain:** Queue depth yang terus naik mengindikasikan consumer lebih lambat dari publisher. Jika mencapai `QUEUE_MAXSIZE` (10.000, dapat dikonfigurasi via env), publisher mendapat HTTP 503 — sinyal untuk slow down dengan exponential backoff (Tanenbaum & Van Steen, 2007, Bab 1–7).

#### 5. Availability
**Definisi:** Persentase waktu sistem dapat menerima event.

**Kaitan desain:** `GET /health` endpoint memungkinkan Docker Compose health check (`interval: 10s, retries: 5`) mendeteksi aggregator yang tidak responsif sebelum publisher mulai mengirim event (`depends_on: condition: service_healthy`).

---

## Bagian Implementasi

### a. Model Event & API

Model event didefinisikan di `src/models.py` menggunakan Pydantic v2:

```python
class Event(BaseModel):
    topic:     str            # Format: [a-zA-Z0-9_\-\.]+, divalidasi regex
    event_id:  str            # UUID v4 atau format unik lainnya
    timestamp: str            # ISO 8601, divalidasi fromisoformat()
    source:    str            # Identifier publisher
    payload:   Dict[str, Any] # Data bebas, default {}
```

**Endpoint yang diimplementasikan:**

| Method | Path | Fungsi |
|---|---|---|
| `POST` | `/publish` | Terima single event, batch object `{"events":[...]}`, atau batch array `[...]` |
| `GET` | `/events?topic=` | Daftar event unik yang sudah diproses, filter opsional per topic |
| `GET` | `/stats` | Statistik: received, unique_processed, duplicate_dropped, duplicate_rate_pct, topics, uptime, queue_size |
| `GET` | `/health` | Health check untuk Docker & monitoring |

**Contoh response `GET /stats`:**
```json
{
  "received": 5000,
  "unique_processed": 3750,
  "duplicate_dropped": 1250,
  "duplicate_rate_pct": 25.0,
  "topics": ["audit-log", "inventory", "notifications", "orders", "payments", "user-events"],
  "uptime_seconds": 45.3,
  "queue_size": 0
}
```

### b. Idempotency & Deduplication

Implementasi di `src/dedup_store.py`:

```python
def store_event(self, event: Dict[str, Any]) -> bool:
    with self._lock:
        conn = self._connect()
        try:
            try:
                conn.execute("""
                    INSERT INTO processed_events
                        (topic, event_id, timestamp, source, payload, processed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (...))
                conn.execute("UPDATE stats SET value = value + 1 WHERE key = 'unique_processed'")
                conn.commit()
                return True   # event unik → disimpan
            except sqlite3.IntegrityError:
                # PRIMARY KEY violation → duplikat
                conn.execute("UPDATE stats SET value = value + 1 WHERE key = 'duplicate_dropped'")
                conn.commit()
                return False  # duplikat → dibuang
        finally:
            conn.close()
```

**Skema SQLite:**
```sql
CREATE TABLE processed_events (
    topic        TEXT NOT NULL,
    event_id     TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    source       TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    processed_at TEXT NOT NULL,
    PRIMARY KEY (topic, event_id)   -- kunci dedup komposit
);
CREATE INDEX idx_topic ON processed_events(topic);  -- optimasi GET /events?topic=

CREATE TABLE stats (
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
-- Keys: received, unique_processed, duplicate_dropped
```

**Logging setiap duplikasi:**
```
✅ PROCESSED  | topic=orders        | event_id=abc-123 | session_total=3750
⚠️  DUPLICATE  | topic=payments      | event_id=xyz-789 | session_drops=1250
```

### c. Reliability & Ordering

**At-least-once delivery** disimulasikan di `publisher/publisher.py`:
```python
n_unique = int(TOTAL_EVENTS * (1 - DUPLICATE_RATE))   # 3750 event unik
n_dup    = TOTAL_EVENTS - n_unique                    # 1250 duplikat

unique_events    = [make_event(random.choice(TOPICS)) for _ in range(n_unique)]
duplicate_events = [
    make_event(topic=..., event_id=random.choice(unique_events)["event_id"])
    for _ in range(n_dup)
]
all_events = unique_events + duplicate_events
random.shuffle(all_events)  # campur untuk simulasi out-of-order
```

**Toleransi crash:** Setelah `docker compose down && docker compose up aggregator`, SQLite di Docker volume masih berisi semua event yang sudah diproses. Event yang sama akan kembali dideteksi sebagai duplikat — diverifikasi di `test_dedup.py::test_dedup_persistence_after_restart`.

**Ordering:** FIFO dalam satu instance (asyncio.Queue). Total ordering tidak diperlukan untuk log aggregation (lihat T5).

### d. Performa Minimum

Diuji di `tests/test_stress.py`:
- **5.000 event** dengan **25% duplikasi** (di atas minimum 20%)
- Semua event diproses langsung via `DedupStore.store_event()`
- Batas waktu: **120 detik** (toleran untuk Windows)
- Verifikasi: `stored_count == 3750`, `dropped_count == 1250`
- Throughput dilaporkan: `events/sec`

### e. Docker

`Dockerfile` aggregator:
```dockerfile
FROM python:3.11-slim
WORKDIR /app

# Security: non-root user
RUN adduser --disabled-password --gecos '' appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

# Dependency caching (layer terpisah dari source code)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
USER appuser

VOLUME ["/app/data"]
EXPOSE 8080

ENV DEDUP_DB_PATH=/app/data/dedup.db \
    PORT=8080 HOST=0.0.0.0 LOG_LEVEL=INFO QUEUE_MAXSIZE=10000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" \
    || exit 1

CMD ["python", "-m", "src.main"]
```

### f. Docker Compose (Bonus +10%)

`docker-compose.yml` mendefinisikan dua service terpisah dalam jaringan internal `aggregator-net`:

```yaml
services:
  aggregator:
    build: { context: ., dockerfile: Dockerfile }
    ports: ["8080:8080"]
    volumes: [dedup-data:/app/data]
    networks: [aggregator-net]
    healthcheck: { interval: 10s, retries: 5, start_period: 15s }
    restart: unless-stopped

  publisher:
    build: { context: ., dockerfile: publisher/Dockerfile }
    environment:
      AGGREGATOR_URL: "http://aggregator:8080"  # DNS internal Docker
      TOTAL_EVENTS: "5000"
      DUPLICATE_RATE: "0.25"
      BATCH_SIZE: "100"
    networks: [aggregator-net]
    depends_on:
      aggregator: { condition: service_healthy }
    restart: "no"
```

Publisher menggunakan nama service `aggregator` sebagai hostname — resolusi DNS dilakukan oleh Docker network secara internal, tanpa layanan eksternal.

### g. Unit Tests

Total **10 test** yang dapat dijalankan dengan `pytest`:

| Test | File | Deskripsi |
|---|---|---|
| T1a | `test_dedup.py` | Dedup dasar: event sama dikirim 2x → hanya 1 tersimpan |
| T1b | `test_dedup.py` | Event_id sama, topic berbeda → bukan duplikat |
| T1c | `test_dedup.py` | Event sama dikirim 10x → hanya 1 tersimpan, 9 dibuang |
| T2a | `test_dedup.py` | Persistensi: instance baru dari DB yang sama tetap mendeteksi duplikat |
| T2b | `test_dedup.py` | `is_duplicate()` konsisten setelah "restart" (instance baru) |
| T3  | `test_dedup.py` | 100 event unik → semua tersimpan, tidak ada yang ditolak |
| T4  | `test_dedup.py` | Stats akurat: 3 unik + 2 duplikat → counter tepat |
| T5  | `test_api.py` | Validasi skema: missing field, timestamp invalid, topic invalid chars |
| T6–T9 | `test_api.py` | API consistency: GET /events, batch dedup, GET /stats, topic filter |
| T10 | `test_stress.py` | Stress: 5.000 event, 25% duplikat, < 120 detik, throughput dilaporkan |

**Menjalankan tests:**
```bash
# Build image dulu
docker build -t uts-aggregator .

# Jalankan semua test
docker run --rm uts-aggregator pytest tests/ -v

# Atau lokal (dengan Python 3.11 + pip install -r requirements.txt)
pytest tests/ -v
```

---

## Keputusan Desain: Ringkasan

| Aspek | Keputusan | Alasan |
|---|---|---|
| **Dedup mechanism** | SQLite `PRIMARY KEY (topic, event_id)` | Atomik, zero race condition, persistent, tanpa external service |
| **Dedup key** | Komposit `(topic, event_id)` | Namespace per topik, event_id sama di topik berbeda = event berbeda |
| **Delivery semantic** | At-least-once + idempotent consumer | Lebih mudah dari exactly-once, efektifitas setara untuk log aggregation |
| **Ordering** | FIFO in-queue, partial ordering | Total ordering tidak dibutuhkan untuk log aggregation lintas topik |
| **Persistence** | SQLite WAL + Docker volume | Embedded, tanpa external service, crash-safe via WAL journal |
| **Concurrency** | `asyncio` + `asyncio.to_thread()` | Non-blocking HTTP handler, thread-safe SQLite access via `threading.Lock()` |
| **Queue** | `asyncio.Queue` (in-memory, max 10.000) | Sederhana, cepat, menyerap lonjakan beban, overflow mengembalikan HTTP 503 |
| **Framework** | FastAPI + Uvicorn | Auto Swagger UI, Pydantic validation, lifespan hooks, async native |
| **Config** | Environment variables | 12-factor app, mudah di-override via Docker Compose environment |

---

## Ringkasan Sistem dan Arsitektur

### Deskripsi Singkat

**Pub-Sub Log Aggregator** adalah layanan berbasis Python yang menerima *event* dari satu atau lebih publisher melalui REST API, memproses event tersebut secara asinkron melalui antrian in-memory, dan menyimpan hanya event yang unik ke dalam database SQLite yang persisten. Sistem menjamin bahwa setiap event dengan kombinasi `(topic, event_id)` yang sama hanya diproses **tepat satu kali**, meskipun dikirim berkali-kali oleh publisher.

### Diagram Alur Sederhana

```
┌──────────────────┐        HTTP POST /publish
│  Publisher       │ ──────────────────────────────────────────────────────┐
│  (Docker svc)    │  { topic, event_id, timestamp, source, payload }      │
│  5.000 event     │                                                        │
│  25% duplikat    │                                                        │
└──────────────────┘                                                        │
                                                                            ▼
                                                           ┌────────────────────────┐
                                                           │    HTTP Layer          │
                                                           │    FastAPI / Uvicorn   │
                                                           │    202 Accepted        │
                                                           └────────────┬───────────┘
                                                                        │ put_nowait()
                                                                        ▼
                                                           ┌────────────────────────┐
                                                           │   asyncio.Queue        │
                                                           │   (in-memory buffer)   │
                                                           │   max 10.000 item      │
                                                           └────────────┬───────────┘
                                                                        │ get() setiap event
                                                                        ▼
                                                           ┌────────────────────────┐
                                                           │  IdempotentConsumer    │
                                                           │  (background task)     │
                                                           │  asyncio.to_thread()   │
                                                           └────────────┬───────────┘
                                                                        │ store_event()
                                              ┌─────────────────────────▼─────────────────┐
                                              │         SQLite DedupStore                 │
                                              │                                           │
                                              │  INSERT → PRIMARY KEY (topic, event_id)  │
                                              │  ✅ Unik  → simpan, unique_processed++    │
                                              │  ❌ Duplikat → buang, duplicate_dropped++ │
                                              │                                           │
                                              │  WAL mode | threading.Lock() | persistent│
                                              └───────────────────────────────────────────┘
                                                        ▲              ▲
                                              GET /events?topic=    GET /stats
```

### Komponen Utama

| Komponen | File | Peran |
|---|---|---|
| **HTTP Layer** | `src/main.py` | Menerima event, validasi Pydantic, memasukkan ke Queue |
| **asyncio.Queue** | `src/main.py` | Buffer in-memory, decoupling ingestion dari processing |
| **IdempotentConsumer** | `src/consumer.py` | Background task, membaca Queue, memanggil DedupStore |
| **DedupStore** | `src/dedup_store.py` | SQLite, PRIMARY KEY dedup, statistik persisten |
| **Models** | `src/models.py` | Pydantic Event/EventBatch, validasi topic & timestamp |
| **Publisher** | `publisher/publisher.py` | Simulasi at-least-once, batch HTTP, health check polling |

---

## Keputusan Desain Detail

### 1. Idempotency

**Definisi yang diimplementasikan:** Sebuah operasi disebut *idempotent* jika menjalankannya satu kali atau berkali-kali menghasilkan efek yang identik. Dalam sistem ini, "mengirim event yang sama N kali" harus menghasilkan state akhir yang sama dengan "mengirim event tersebut satu kali".

**Mekanisme:**
- Kunci idempotency adalah kombinasi **`(topic, event_id)`** — bukan hanya `event_id`
- `DedupStore.store_event()` menggunakan `INSERT` dengan `PRIMARY KEY (topic, event_id)`
- Jika event sudah ada → SQLite melempar `IntegrityError` secara **atomik**
- Tidak ada window race condition karena tidak menggunakan pola SELECT-lalu-INSERT

```python
try:
    conn.execute("INSERT INTO processed_events (...) VALUES (...)")
    # Berhasil → event unik
    return True
except sqlite3.IntegrityError:
    # PRIMARY KEY violation → duplikat, tidak ada efek samping
    return False
```

**Mengapa tidak pakai SELECT dulu?** Pola SELECT-kemudian-INSERT rentan *time-of-check-to-time-of-use (TOCTOU) race condition* — dua thread bisa sama-sama melihat "belum ada" lalu keduanya INSERT. `PRIMARY KEY` constraint menghilangkan race condition ini di level database engine.

---

### 2. Dedup Store

**Pilihan teknologi: SQLite**

SQLite dipilih sebagai dedup store karena:

| Kriteria | SQLite | Alternatif (Redis, file JSON) |
|---|---|---|
| **Persistent** | ✅ File di disk | Redis: perlu konfigurasi AOF/RDB |
| **Tanpa server eksternal** | ✅ Embedded | Redis: butuh process terpisah |
| **ACID transactions** | ✅ Native | File JSON: tidak ada atomicity |
| **PRIMARY KEY constraint** | ✅ Native | File JSON: harus implementasi manual |
| **Docker volume** | ✅ Mount langsung | Sama |
| **Concurrency** | ✅ WAL + Lock | Redis: lebih baik tapi overkill |

**Konfigurasi SQLite yang digunakan:**
```sql
PRAGMA journal_mode = WAL;       -- Write-Ahead Logging: concurrency lebih baik
PRAGMA synchronous = NORMAL;     -- Keseimbangan durability vs performa
```

**WAL (Write-Ahead Logging):** Dalam mode WAL, write tidak langsung mengubah file database utama — ditulis ke file WAL terpisah terlebih dahulu. Ini memungkinkan reader tidak terblokir oleh writer, meningkatkan throughput concurrent read (GET /events, GET /stats) saat consumer sedang menulis.

**Thread-safety:** `threading.Lock()` digunakan untuk serialisasi akses karena `asyncio.to_thread()` menjalankan operasi SQLite di thread pool. SQLite dengan mode WAL mendukung *multiple reader, single writer* — Lock memastikan hanya satu writer aktif pada satu waktu.

**Skema tabel:**
```sql
CREATE TABLE processed_events (
    topic        TEXT NOT NULL,
    event_id     TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    source       TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    processed_at TEXT NOT NULL,
    PRIMARY KEY (topic, event_id)   -- kunci dedup
);
CREATE INDEX idx_topic ON processed_events(topic);  -- optimasi GET /events?topic=

CREATE TABLE stats (
    key   TEXT PRIMARY KEY,         -- 'received' | 'unique_processed' | 'duplicate_dropped'
    value INTEGER NOT NULL DEFAULT 0
);
```

---

### 3. Ordering

**Keputusan: Partial ordering (FIFO within queue), total ordering tidak diterapkan**

Dalam sistem ini, `asyncio.Queue` menjamin **FIFO ordering** — event yang masuk lebih dulu diproses lebih dulu dalam satu instance aggregator. Namun **total ordering** lintas topik tidak diterapkan dan memang tidak diperlukan, karena:

1. **Independence antar topik:** Event `orders` dan `payments` tidak memiliki causal dependency. Urutan relatif keduanya tidak mempengaruhi kebenaran hasil aggregasi.
2. **Aggregation semantics:** Tujuan sistem adalah mengumpulkan event unik, bukan mengeksekusi state machine yang urutan-sensitif.
3. **Cost-benefit:** Implementasi total ordering memerlukan *logical clock* (Lamport clock) atau *vector clock* — overhead signifikan tanpa manfaat nyata untuk use case ini.

**Apa yang dijamin:**
- Event dari publisher yang sama dengan batch yang sama → diproses berurutan (FIFO)
- `timestamp` (ISO 8601, di-generate publisher) tersimpan dan dapat digunakan downstream untuk reordering jika diperlukan
- `processed_at` (waktu consumer memproses) tersedia di setiap event di database

**Keterbatasan yang diterima:**
- *Clock skew* antar publisher dapat menyebabkan event dengan `timestamp` lebih lama tiba lebih akhir
- Event dari publisher berbeda dapat tiba out-of-order — diterima sebagai trade-off yang wajar untuk log aggregation

---

### 4. Retry dan Fault Tolerance

**Strategi retry di publisher:**

Publisher menggunakan *health check polling* sebelum mengirim event:
```python
def wait_for_aggregator(url, max_retries=30, delay=2.0):
    for attempt in range(1, max_retries + 1):
        try:
            resp = httpx.get(f"{url}/health", timeout=5.0)
            if resp.status_code == 200:
                return  # aggregator siap
        except httpx.RequestError:
            pass
        time.sleep(delay)
    sys.exit(1)  # gagal setelah max_retries
```

**Simulasi at-least-once delivery:**
Publisher secara sengaja mengirim 25% event yang `event_id`-nya sudah pernah dikirim sebelumnya, merepresentasikan skenario retry nyata (timeout, network fluke, atau duplicate push dari message broker upstream).

**Respons terhadap queue penuh (HTTP 503):**
```python
except asyncio.QueueFull:
    raise HTTPException(
        status_code=503,
        detail=f"Queue penuh ({queue.maxsize} item). Berhasil di-queue: {queued}/{total}. Coba lagi."
    )
```
Publisher yang menerima 503 seharusnya mengimplementasikan *exponential backoff* sebelum retry — sinyal backpressure yang eksplisit.

**Toleransi crash container:**
- Event yang sudah di-`commit` ke SQLite sebelum crash → **aman**, WAL menjamin durability
- Event yang masih di `asyncio.Queue` (belum di-consume) saat crash → **hilang**, namun publisher dapat mengirim ulang (at-least-once)
- Setelah restart, DedupStore dari SQLite yang sama akan mengenali event yang sudah pernah diproses → tidak ada reprocessing

---

## Analisis Performa dan Metrik

### Desain Pipeline dan Dampak Performa

Sistem menggunakan **pipeline dua tahap** yang memisahkan ingestion dari processing:

```
Tahap 1: Ingestion (HTTP Handler)
  POST /publish → validasi Pydantic → queue.put_nowait() → return 202
  Waktu: ~1–5ms per request (non-blocking, tidak menunggu SQLite)

Tahap 2: Processing (Background Consumer)
  queue.get() → asyncio.to_thread(store_event) → SQLite INSERT/IntegrityError
  Waktu: ~10–30ms per event (sequential, terikat threading.Lock)
```

Pemisahan ini berarti **HTTP handler tetap responsif** meskipun SQLite sedang menulis. Publisher tidak perlu menunggu database selesai — cukup event masuk queue, langsung dapat `202 Accepted`.

### Metrik yang Diukur

#### Throughput DedupStore (Stress Test)

Diukur di `tests/test_stress.py` — 5.000 event langsung ke DedupStore tanpa HTTP overhead:

| Parameter | Nilai |
|---|---|
| Total event | 5.000 |
| Event unik | 3.750 (75%) |
| Event duplikat | 1.250 (25%) |
| Batas waktu | < 120 detik |
| Throughput (estimasi) | ~50–200 events/sec (tergantung hardware) |

> **Catatan:** Jalankan `pytest tests/test_stress.py -v -s` untuk melihat throughput aktual di mesin Anda. Hasil dicetak di output test.

#### Latency End-to-End

| Komponen | Estimasi Latency |
|---|---|
| HTTP parsing + Pydantic validation | ~1–3ms |
| `queue.put_nowait()` | < 0.1ms |
| `queue.get()` di consumer | < 0.1ms |
| `asyncio.to_thread()` context switch | ~0.5ms |
| SQLite `INSERT` (WAL mode) | ~5–20ms |
| **Total end-to-end** | **~7–25ms per event** |

Latency antara event diterima di `POST /publish` hingga tersedia di `GET /events` tergantung backlog queue — saat queue kosong, latency minimal. Saat banyak event menumpuk, latency bertambah linier dengan `queue_size`.

#### Duplicate Rate

Tersedia secara real-time di `GET /stats`:

```json
{
  "received": 5000,
  "unique_processed": 3750,
  "duplicate_dropped": 1250,
  "duplicate_rate_pct": 25.0
}
```

Formula kalkulasi di `src/main.py`:
```python
duplicate_rate = (duplicate_dropped / received * 100) if received > 0 else 0.0
```

**Interpretasi:**
- `duplicate_rate_pct` ≈ 25% → normal, sesuai konfigurasi publisher
- `duplicate_rate_pct` > 50% → publisher terlalu agresif retry atau ada network issue
- `duplicate_rate_pct` = 0% → publisher tidak pernah retry (potensi event loss)

#### Queue Depth (Backpressure Indicator)

`queue_size` di `GET /stats` dan `GET /health` adalah indikator backpressure real-time:

| `queue_size` | Interpretasi | Tindakan |
|---|---|---|
| 0 | Consumer memproses lebih cepat dari publisher | Normal |
| 1–1.000 | Ada backlog ringan | Monitor |
| 1.000–9.000 | Consumer kewalahan | Pertimbangkan rate limiting publisher |
| ≥ 10.000 | Queue penuh | Publisher mendapat HTTP 503, harus backoff |

#### Availability

`GET /health` endpoint dikonfigurasi sebagai HEALTHCHECK di Dockerfile dan Docker Compose:
```
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3
```

Docker menandai container sebagai `unhealthy` setelah 3 kali gagal → Docker Compose publisher tidak akan mulai mengirim event sebelum aggregator `healthy` (`depends_on: condition: service_healthy`).

### Bottleneck dan Optimasi Potensial

| Bottleneck | Penyebab | Solusi Potensial |
|---|---|---|
| SQLite sequential write | `threading.Lock()` serialisasi semua write | Batch INSERT dalam satu transaksi |
| Single consumer | Satu goroutine memproses event | Beberapa consumer worker paralel |
| In-memory queue | Data hilang saat crash | Persistent queue (Redis Streams, SQLite queue table) |
| SQLite write lock | WAL tetap single-writer | Upgrade ke PostgreSQL untuk throughput tinggi |

Untuk skala UTS dengan 5.000 event, bottleneck di atas tidak signifikan. Sistem tetap responsif dan menyelesaikan seluruh beban dalam waktu yang wajar. Optimasi diperlukan hanya jika throughput target > ~500 events/sec secara sustained.

---

## Referensi

Tanenbaum, A. S., & Van Steen, M. (2007). *Distributed systems: Principles and paradigms* (2nd ed.). Prentice Hall.

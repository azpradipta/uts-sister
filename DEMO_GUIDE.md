# 🎬 Panduan Video Demo — Pub-Sub Log Aggregator
# Durasi target: 5–8 menit

> 💬 **Cara pakai panduan ini:**
> Teks di blok `🎙️ SCRIPT` adalah kalimat yang kamu baca keras-keras saat rekam.
> Teks di blok `> Jelaskan:` adalah petunjuk aksi yang kamu lakukan di layar.

---

## Persiapan Sebelum Rekam
1. **Buka Docker Desktop** → tunggu statusnya "Engine Running" (ikon Docker di taskbar hijau)
2. **Buka 1 jendela PowerShell** → arahkan ke folder proyek:
   ```powershell
   cd C:\uts_sister
   ```
3. **Siapkan browser** (Chrome/Edge) → nanti buka ke `http://localhost:8080/docs`

---

## ═══════════════════════════════════════════
## SCENE 1 — Build & Jalankan (Terminal) ±2 menit
## ═══════════════════════════════════════════

### Step 1: Build image Docker

```powershell
docker build -t uts-aggregator .
```

> **Aksi:** Jalankan perintah di atas, tunggu hingga selesai.

---

> 🎙️ **SCRIPT — Bacakan saat build berjalan:**
>
> *"Halo, pada video ini saya akan mendemonstrasikan proyek UTS Sistem Terdistribusi —
> sebuah Pub-Sub Log Aggregator yang mengimplementasikan konsep Idempotent Consumer
> dan Deduplication berbasis SQLite.*
>
> *Pertama, kita build Docker image-nya terlebih dahulu.
> Di sini saya menggunakan base image Python 3.11 slim untuk ukuran yang ringan,
> ditambah non-root user untuk keamanan container.*
>
> *Tunggu sebentar sampai proses build selesai..."*

---

### Step 2: Jalankan dengan Docker Compose (aggregator + publisher sekaligus)

```powershell
docker compose up --build
```

> **Aksi:** Jalankan perintah, tunjukkan log yang mulai berjalan di terminal.

---

> 🎙️ **SCRIPT — Bacakan saat log mulai muncul:**
>
> *"Sekarang kita jalankan dengan Docker Compose.
> Docker Compose akan menjalankan DUA service secara bersamaan:*
>
> *Pertama, service **aggregator** — ini adalah server FastAPI yang bertugas
> menerima event dari publisher, lalu memprosesnya secara asinkron.*
>
> *Kedua, service **publisher** — ini adalah script Python yang secara otomatis
> mengirimkan 5.000 event ke aggregator, di mana 25% di antaranya adalah
> event duplikat yang disengaja, untuk mensimulasikan kondisi at-least-once delivery
> yang sering terjadi di sistem terdistribusi nyata."*

**Log yang muncul di terminal:**
```
uts-aggregator  | 🚀 Starting Pub-Sub Log Aggregator...
uts-aggregator  | ✅ Aggregator ready — waiting for events
uts-publisher   | ✅ Aggregator siap setelah 3 percobaan
uts-publisher   | 📤 Batch 1 | sent=100 | total_sent=100
uts-publisher   | 📤 Batch 2 | sent=100 | total_sent=200
...
uts-aggregator  | ✅ PROCESSED  | topic=orders    | event_id=...
uts-aggregator  | ⚠️  DUPLICATE  | topic=payments  | event_id=...
```

---

> 🎙️ **SCRIPT — Bacakan sambil menunjuk log:**
>
> *"Perhatikan dua jenis baris log yang muncul di sini.*
>
> *Baris dengan tanda centang hijau — **PROCESSED** — artinya event tersebut
> adalah event unik yang berhasil diterima dan disimpan ke database.*
>
> *Sedangkan baris dengan tanda seru kuning — **DUPLICATE** — artinya
> event dengan ID yang sama sudah pernah diproses sebelumnya,
> sehingga langsung dibuang tanpa disimpan ulang.*
>
> *Inilah mekanisme deduplication yang bekerja secara real-time.*
>
> *Kita tunggu sampai publisher selesai mengirim semua 5.000 event..."*

Tunggu sampai publisher selesai (muncul: `Final stats: ...`)

---

## ═══════════════════════════════════════════
## SCENE 2 — Buka Swagger UI (Browser) ±30 detik
## ═══════════════════════════════════════════

Buka browser, ketik di address bar:
```
http://localhost:8080/docs
```

> **Aksi:** Buka browser, navigasi ke URL di atas, tunjukkan halaman Swagger UI.

---

> 🎙️ **SCRIPT — Bacakan saat Swagger UI terbuka:**
>
> *"Publisher sudah selesai. Sekarang kita buka browser untuk mengakses
> Swagger UI yang disediakan otomatis oleh FastAPI.*
>
> *Di sini kita bisa melihat dan mencoba semua endpoint REST API
> secara visual, tanpa perlu tools tambahan seperti Postman atau curl.*
>
> *Tersedia empat endpoint utama:*
> *- POST /publish — untuk mengirim event baru*
> *- GET /events — untuk melihat event yang sudah tersimpan*
> *- GET /stats — untuk melihat statistik sistem secara keseluruhan*
> *- GET /health — untuk mengecek status server*"*

Tunjukkan daftar endpoint yang tersedia:
- `POST /publish`
- `GET /events`
- `GET /stats`
- `GET /health`

---

## ═══════════════════════════════════════════
## SCENE 3 — Cek Stats Setelah Publisher Selesai ±1 menit
## ═══════════════════════════════════════════

> **Aksi:** Di Swagger UI, klik **`GET /stats`** → klik **"Try it out"** → klik **"Execute"**

---

> 🎙️ **SCRIPT — Bacakan sebelum klik Execute:**
>
> *"Pertama kita cek statistik sistem menggunakan endpoint GET /stats.
> Kita klik 'Try it out', lalu 'Execute'..."*

**Output yang akan muncul (hasil dari 5.000 event publisher):**
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

---

> 🎙️ **SCRIPT — Bacakan sambil menunjuk tiap field di response:**
>
> *"Hasil statistiknya sangat jelas.*
>
> ***received: 5.000*** — ini total event yang masuk ke sistem, sesuai dengan
> jumlah yang dikirim publisher tadi.*
>
> ***unique_processed: 3.750*** — dari 5.000 event, hanya 3.750 yang benar-benar
> unik dan berhasil disimpan ke database.*
>
> ***duplicate_dropped: 1.250*** — sisanya, yaitu 1.250 event, adalah duplikat
> yang berhasil dideteksi dan dibuang oleh sistem.*
>
> ***duplicate_rate_pct: 25.0*** — ini persis 25 persen, sesuai dengan konfigurasi
> publisher yang memang sengaja kita set untuk mengirim 25% event duplikat.*
>
> ***queue_size: 0*** — artinya tidak ada event yang mengantre, semua sudah
> selesai diproses.*
>
> *Angka-angka ini membuktikan bahwa sistem deduplication kita bekerja
> dengan akurat dan konsisten."*

---

## ═══════════════════════════════════════════
## SCENE 4 — Demo Idempotency Manual via Swagger ±2 menit
## [BAGIAN PALING PENTING]
## ═══════════════════════════════════════════

### Step 4a: Kirim event BARU yang unik

> **Aksi:** Di Swagger UI klik **`POST /publish`** → **"Try it out"**

---

> 🎙️ **SCRIPT — Bacakan sebelum mengisi body:**
>
> *"Sekarang kita akan demonstrasikan konsep Idempotent Consumer secara langsung.*
>
> *Saya akan mengirim satu event baru secara manual menggunakan endpoint POST /publish.
> Saya isi topic-nya 'demo-live', dengan event_id unik 'demo-event-001'."*

Ganti isi body dengan:
```json
{
  "topic": "demo-live",
  "event_id": "demo-event-001",
  "timestamp": "2024-01-15T10:00:00Z",
  "source": "live-demo",
  "payload": {"pesan": "ini event pertama"}
}
```

> **Aksi:** Klik **"Execute"**

**Respons:** `{"status": "accepted", "queued": 1, "total": 1, "queue_size": 0}`

**Di terminal tunjukkan:**
```
✅ PROCESSED  | topic=demo-live | event_id=demo-event-001
```

---

> 🎙️ **SCRIPT — Bacakan setelah response muncul:**
>
> *"Server merespons dengan status 'accepted'. Dan di terminal kita bisa lihat
> baris PROCESSED — event berhasil diterima dan disimpan.*
>
> *Sekarang, saya akan kirim **event yang persis sama** — event_id yang sama,
> topic yang sama, payload yang sama — untuk mensimulasikan kondisi retry
> yang terjadi di sistem terdistribusi ketika sebuah message dikirim ulang."*

---

### Step 4b: Kirim event YANG SAMA persis (simulasi retry)

> **Aksi:** Di Swagger UI, klik **"Execute" lagi** (jangan ubah apapun di body!)

**Respons:** tetap `{"status": "accepted", "queued": 1}` (HTTP layer menerima)

**Tapi di terminal tunjukkan:**
```
⚠️  DUPLICATE  | topic=demo-live | event_id=demo-event-001
```

---

> 🎙️ **SCRIPT — Bacakan setelah response muncul:**
>
> *"Menarik! HTTP response-nya tetap 202 Accepted — artinya secara protokol HTTP,
> request berhasil diterima.*
>
> *Tapi lihat di terminal — bukan PROCESSED, melainkan **DUPLICATE**!*
>
> *Consumer kita mendeteksi bahwa event dengan ID 'demo-event-001' ini
> sudah pernah diproses sebelumnya. Maka event ini langsung dibuang —
> tidak disimpan ulang ke database.*
>
> *Inilah yang disebut **Idempotent Consumer**: meskipun event yang sama
> dikirim berkali-kali, efeknya tetap sama seperti dikirim sekali saja."*

---

### Step 4c: Verifikasi di GET /events

> **Aksi:** Klik **`GET /events`** → **"Try it out"** → isi `topic`: `demo-live` → **"Execute"**

```json
{
  "topic": "demo-live",
  "count": 1,
  "events": [
    {
      "topic": "demo-live",
      "event_id": "demo-event-001",
      "payload": {"pesan": "ini event pertama"},
      ...
    }
  ]
}
```

---

> 🎙️ **SCRIPT — Bacakan sambil menunjuk field count:**
>
> *"Kita verifikasi dengan GET /events untuk topic 'demo-live'.*
>
> *Hasilnya: count hanya **1**. Meskipun kita sudah kirim event yang sama dua kali,
> di database hanya tersimpan satu event saja.*
>
> *Tidak ada duplikat. Inilah **Deduplication** yang bekerja di level storage."*

---

### Step 4d: Cek stats lagi → duplicate_dropped bertambah

> **Aksi:** Klik **`GET /stats`** → **"Execute"**

---

> 🎙️ **SCRIPT — Bacakan sambil menunjuk perubahan angka:**
>
> *"Terakhir, kita cek stats sekali lagi. Perhatikan — angka **duplicate_dropped**
> sekarang bertambah satu dibanding tadi, karena kita baru saja mengirim satu duplikat.*
>
> *Sedangkan **unique_processed** tidak berubah — membuktikan bahwa
> event duplikat tadi memang tidak disimpan."*

---

## ═══════════════════════════════════════════
## SCENE 5 — Restart Container = Uji Persistensi ±1.5 menit
## ═══════════════════════════════════════════

### Step 5a: Stop semua service

> **Aksi:** Di terminal tekan `Ctrl+C` untuk stop docker compose, lalu jalankan:

```powershell
docker compose down
```

---

> 🎙️ **SCRIPT — Bacakan saat container berhenti:**
>
> *"Sekarang kita uji fitur persistensi. Saya akan matikan semua container —
> ini mensimulasikan kondisi server crash, maintenance, atau restart.*
>
> *Pertanyaannya: apakah setelah container dinyalakan ulang, sistem masih
> ingat event mana yang sudah diproses sebelumnya?"*

---

### Step 5b: Jalankan ulang HANYA aggregator (tanpa publisher)

```powershell
docker compose up aggregator
```

> **Aksi:** Tunggu aggregator ready (muncul log `✅ Aggregator ready`)

---

> 🎙️ **SCRIPT — Bacakan saat aggregator restart:**
>
> *"Saya nyalakan ulang hanya service aggregator-nya saja, tanpa publisher.*
>
> *Data di SQLite tersimpan di Docker volume yang persist — tidak ikut terhapus
> saat container di-restart. Kita akan buktikan ini sekarang."*

---

### Step 5c: Kirim ulang event demo yang sama via Swagger

> **Aksi:** Buka lagi `http://localhost:8080/docs`

> **Aksi:** Klik **`GET /stats`** → **"Execute"**

---

> 🎙️ **SCRIPT — Bacakan saat stats muncul:**
>
> *"Lihat — stats sudah ada isinya meskipun container baru saja restart!
> Data unique_processed dan duplicate_dropped dari sesi sebelumnya masih ada.*
>
> *Sekarang kita kirim ulang event 'demo-event-001' yang sama..."*

> **Aksi:** Klik **`POST /publish`** → kirim event `demo-event-001` lagi:

```json
{
  "topic": "demo-live",
  "event_id": "demo-event-001",
  "timestamp": "2024-01-15T10:00:00Z",
  "source": "live-demo",
  "payload": {"pesan": "ini event pertama"}
}
```

**Di terminal tunjukkan:**
```
⚠️  DUPLICATE  | topic=demo-live | event_id=demo-event-001
```

---

> 🎙️ **SCRIPT — Bacakan setelah DUPLICATE muncul di terminal:**
>
> *"Dan hasilnya — **DUPLICATE**! Meskipun container sudah di-restart sepenuhnya,
> sistem masih mengenali bahwa event 'demo-event-001' ini sudah pernah diproses.*
>
> *Ini karena SQLite disimpan di Docker volume yang persist melewati lifecycle container.*
>
> *Inilah yang disebut **Dedup Store yang tahan restart** — jaminan idempotency
> tidak hilang meskipun server padam."*

---

## ═══════════════════════════════════════════
## SCENE 6 — Ringkasan Arsitektur ±30-60 detik
## ═══════════════════════════════════════════

> **Aksi:** Sambil menunjukkan Swagger UI atau terminal.

---

> 🎙️ **SCRIPT — Bacakan untuk penutup:**
>
> *"Sebagai penutup, saya akan rangkum arsitektur sistem ini.*
>
> *Sistem terdiri dari empat komponen utama:*
>
> *Pertama, **Publisher** — bertugas mengirim event via POST /publish,
> bisa single event, batch, maupun array.*
>
> *Kedua, **asyncio Queue** — ini adalah buffer in-memory yang memisahkan
> proses penerimaan dari proses pemrosesan, sehingga server tetap responsif
> meskipun sedang memproses banyak event.*
>
> *Ketiga, **Idempotent Consumer** — background task yang membaca event
> dari queue dan memprosesnya satu per satu dengan pengecekan duplikat.*
>
> *Keempat, **SQLite DedupStore** — penyimpanan yang menggunakan PRIMARY KEY
> constraint untuk menolak event duplikat secara atomik di level database.*
>
> *Hasilnya: sistem ini menjamin setiap event hanya diproses **tepat satu kali**,
> meskipun dikirim berkali-kali.*
>
> *Ini adalah implementasi dari konsep **exactly-once semantics**,
> yang dicapai melalui kombinasi **at-least-once delivery** di sisi publisher
> dan **idempotent consumer** di sisi aggregator.*
>
> *Terima kasih, sekian demonstrasi dari saya."*

---

## Tips Rekaman

| Tips | Detail |
|---|---|
| 🖥️ Layout | Terminal di kiri, browser Swagger di kanan |
| 🔍 Zoom | Perbesar font terminal agar teks terbaca di video |
| ⏸️ Pause | Beri jeda 2-3 detik setelah setiap hasil muncul |
| 🎯 Highlight | Tunjukkan `✅ PROCESSED` vs `⚠️ DUPLICATE` di terminal |
| 📊 Stats | Screenshot stats sebelum dan sesudah untuk laporan |
| 🎙️ Script | Baca script natural, boleh paraphrase — jangan kaku |
| 🔄 Reset | Sebelum rekam final: `docker compose down -v` dulu |

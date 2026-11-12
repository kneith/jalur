# JALUR — Pendamping Eksplorasi Pendidikan Tinggi

Aplikasi frontend asli JALUR dipertahankan (HTML/CSS/JavaScript) dan backend terpusat dimigrasikan ke Python + FastAPI. Dataset workbook asli tidak diganti dengan data dummy.

## Fitur frontend yang dipertahankan
Dashboard, profil akademik, pencarian program studi, pencarian institusi, detail program, perbandingan, Plan B, blind-spot detector, ringkasan keputusan, sumber resmi, pemeriksaan realitas program, similarity explorer, perencana jalur alternatif, preview kehidupan kampus, perencana biaya, Decision Journal, konsultasi BK, curhat, portal sekolah, dan portal BK.

Sebagian fitur eksplorasi dan alat keputusan tetap berjalan secara lokal di browser sebagaimana pada source asli. Modul sekolah/BK terpusat memerlukan database dan endpoint yang telah dimigrasikan; lihat status migrasi di `docs/MIGRATION_STATUS.md`.

## Data sumber
- `data/database.js`: snapshot operasional asli dari workbook, 4.303 institusi dan 34.709 program studi.
- `data/JALUR_Database_Enriched_2026-11-01.xlsx`: workbook lengkap sumber asli.

Data tidak diperbarui otomatis. Skor kosong bukan nol dan estimasi skor tidak boleh dianggap sebagai skor penerimaan resmi.

## Menjalankan frontend dan API lokal
Persyaratan: Python 3.11+, PostgreSQL 14+ (untuk autentikasi dan Journal tersimpan di server).

1. Buat database PostgreSQL dan jalankan SQL migration berurutan:
   `backend/migrations/001_initial.sql`, lalu `backend/migrations/002_decision_journal.sql`.
2. Salin `backend/.env.example` menjadi `backend/.env`, lalu isi `DATABASE_URL` dan `SESSION_PEPPER` (minimal 32 karakter acak). Untuk lokal, `COOKIE_SECURE=false`.
3. Instal dependency:
   `cd backend`
   `python -m venv .venv`
   Windows: `.venv\\Scripts\\activate`
   macOS/Linux: `source .venv/bin/activate`
   `pip install -r requirements.txt`
4. (Opsional, untuk pencarian direktori via PostgreSQL) Setelah menjalankan migration, dari root jalankan `python backend/scripts/import_directory.py`, lalu atur `DIRECTORY_BACKEND=postgres` di `backend/.env`. Default `json` membaca snapshot asli langsung tanpa impor.
5. Buat administrator pertama dengan `python backend/scripts/bootstrap_admin.py` setelah database dan `.env` siap.
6. Jalankan API dari folder proyek:
   `uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000`
   Jika terminal berada di folder `backend`, gunakan `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`.
7. Pada `index.html`, atur `window.JALUR_API_BASE` sebelum `central.js` ke `http://127.0.0.1:8000/api` (nilai awal di `index.html` sudah diarahkan ke localhost). Contoh tag script konfigurasi dapat dilihat di `docs/INSTALLATION.md`.
8. Sajikan frontend dari root proyek: `python -m http.server 5500 --bind 127.0.0.1`, lalu buka `http://127.0.0.1:5500`.

API health: `http://127.0.0.1:8000/api/health`; dokumentasi OpenAPI: `http://127.0.0.1:8000/docs`.

## Tes
Dari root proyek:
`python -m pytest backend/tests -q`

Tes membutuhkan dependency pada `backend/requirements.txt`. Database tidak diperlukan untuk tes repository direktori.

## Deployment
Frontend statis dapat dipasang di Vercel. Backend FastAPI dan PostgreSQL perlu layanan runtime/database yang mendukung Python dan koneksi persisten; jangan menaruh API FastAPI sebagai static frontend deployment. Lihat `docs/DEPLOYMENT.md`.

## Keamanan dan batasan
- Gunakan HTTPS dan `COOKIE_SECURE=true` di production.
- Ganti semua secret contoh dengan secret kuat dan unik.
- Batasi CORS ke origin frontend yang benar.
- Buat backup dan kebijakan retensi data.
- Fitur curhat anonim harus melalui tinjauan privasi, keamanan, moderasi, dan prosedur eskalasi sebelum dipakai publik.
- Jangan masukkan data siswa, nilai, atau catatan konseling nyata sebelum pengujian keamanan dan kebijakan sekolah selesai.

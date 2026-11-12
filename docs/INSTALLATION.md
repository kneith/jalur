# Panduan instalasi JALUR

## 1. PostgreSQL
Buat database `jalur`, kemudian jalankan:
```bash
psql "$DATABASE_URL" -f backend/migrations/001_initial.sql
psql "$DATABASE_URL" -f backend/migrations/002_decision_journal.sql
```
Pastikan database dapat diakses oleh user aplikasi.

## 2. Konfigurasi backend
Salin `backend/.env.example` menjadi `backend/.env`. Isi `DATABASE_URL`, `SESSION_PEPPER` dan `FRONTEND_ORIGIN`. Jangan commit file `.env`.

## 3. Instalasi Python
```bash
python -m venv backend/.venv
# Windows PowerShell:
backend\.venv\Scripts\Activate.ps1
# macOS/Linux:
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
```

## 4. Jalankan API
Dari root:
```bash
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```
Jika menjalankan dari folder `backend`, hilangkan `--app-dir backend`.

## 5. Hubungkan frontend
Tambahkan konfigurasi sebelum `central.js` dimuat. Pada akhir `<head>` atau sebelum script `central.js`:
```html
<script>window.JALUR_API_BASE = "http://127.0.0.1:8000/api";</script>
```
Jalankan server statis:
```bash
python -m http.server 5500 --bind 127.0.0.1
```
Buka `http://127.0.0.1:5500`.

## 6. Akun
API login memerlukan akun yang sudah dibuat oleh administrator melalui database/bootstrap provisioning. Pembuatan akun mandiri publik tidak diaktifkan pada source asli.

## 7. Import direktori dan administrator awal (opsional)
Untuk menjalankan pencarian dari PostgreSQL, jalankan dari root:
```bash
python backend/scripts/import_directory.py
```
Kemudian atur `DIRECTORY_BACKEND=postgres` pada `backend/.env` dan restart API. Tanpa langkah ini, API memakai snapshot JSON asli dari `data/database.js`.

Buat admin platform pertama:
```bash
python backend/scripts/bootstrap_admin.py
```
Skrip meminta email, nama, dan password melalui terminal (password minimal 14 karakter); password tidak ditulis ke file konfigurasi.

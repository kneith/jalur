# Deployment JALUR

## Arsitektur yang disarankan
- Frontend HTML/CSS/JS: Vercel static hosting.
- Backend FastAPI: layanan Python container/ASGI terpisah (misalnya Render, Railway, Fly.io, atau VPS).
- Database: PostgreSQL terkelola, private network bila tersedia.

Vercel static hosting tidak menjalankan server FastAPI sebagai proses ASGI yang selalu hidup. Pisahkan frontend dan API agar lifecycle, dependency Python, koneksi PostgreSQL, dan logging backend dikelola runtime Python.

## Frontend Vercel
Atur project root ke folder frontend (root repository), framework preset `Other`, build command kosong, output directory `.`. Pastikan `index.html` tersedia di root. Tambahkan konfigurasi `window.JALUR_API_BASE` sebelum `central.js` dengan URL HTTPS backend.

## Backend container
Build dari root repository menggunakan `backend/Dockerfile`:
```bash
docker build -f backend/Dockerfile -t jalur-api .
docker run --env-file backend/.env -p 8000:8000 jalur-api
```
Environment production:
- `DATABASE_URL`
- `SESSION_PEPPER` (random minimal 32 karakter)
- `FRONTEND_ORIGIN` / `CORS_ORIGINS`
- `SESSION_TTL_HOURS`
- `COOKIE_SECURE=true`
- `JALUR_DIRECTORY_FILE=/app/data/database.js`

Jalankan migration SQL secara terpisah terhadap database production sebelum menyalakan API. Gunakan HTTPS pada frontend dan backend; konfigurasi cookie cross-site `SameSite=None; Secure` bila frontend dan API berada pada site berbeda.

## Pemeriksaan sebelum rilis
- Uji `/api/health` dan `/api/directory/search`.
- Uji login, logout, expiry session, CSRF, dan akses lintas peran.
- Uji CORS dari origin frontend production.
- Uji backup/restore PostgreSQL.
- Uji beban direktori dan memori container.
- Pastikan endpoint sekolah/BK yang belum dimigrasikan tidak dipakai.
- Jalankan pengujian browser end-to-end dan security review.

Paket ini belum di-deploy dan tidak boleh disebut production-ready.

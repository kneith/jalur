# JALUR Central Backend (fondasi API)

Backend Node.js + Express + PostgreSQL untuk memindahkan data sekolah dari `localStorage` ke penyimpanan terpusat, dengan sesi server dan izin berbasis peran. Backend ini merupakan layanan terpisah dari UI statis yang ada; UI lama belum otomatis terhubung ke API. Jangan memasukkan data siswa sungguhan sebelum integrasi frontend, deployment HTTPS, dan uji keamanan selesai.

## Fitur dan peran

- `student`: hanya melihat rapor miliknya sendiri; mengajukan konsultasi BK.
- `teacher`: mengelola nilai hanya pada kelas/mata pelajaran/tahun ajaran yang ditugaskan kepadanya.
- `school_admin`: mengelola akun dasar sekolah, kelas, penugasan guru, rapor sekolah, dan data alumni.
- `counselor`: melihat permintaan konsultasi BK dalam sekolahnya dan memperbarui statusnya.
- `wellbeing_moderator`: peran terpisah yang secara eksplisit ditunjuk untuk menangani kotak curhat anonim; tidak memperoleh identitas pengirim karena tidak dikumpulkan.
- `platform_admin`: peran administratif lintas sekolah yang harus sangat dibatasi. API saat ini tidak menyediakan endpoint UI umum untuk peran ini.

## Mulai lokal dengan Docker

1. Pasang Docker Desktop.
2. Salin `.env.example` menjadi `.env` di folder `server`.
3. Buat nilai rahasia yang kuat:
   - `SESSION_PEPPER`: string acak panjang minimal 32 karakter.
   - `VENTING_ENCRYPTION_KEY`: hasil `openssl rand -base64 32`.
   - `POSTGRES_PASSWORD`: kata sandi database acak yang kuat.
4. Ubah `FRONTEND_ORIGIN` ke origin UI yang tepat. Hindari membuka API publik sebelum memasang HTTPS dan reverse proxy.
5. Jalankan dari folder `server`: `docker compose up --build -d`.
6. Bootstrap akun admin sekolah satu kali. Tambahkan `SCHOOL_NAME`, `SCHOOL_CODE`, `ADMIN_NAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` ke `.env`, lalu jalankan `docker compose exec api node src/bootstrap-admin.js`. Jangan simpan kredensial bootstrap di repositori.

### Bootstrap admin

Di mesin yang memiliki Node.js:

```sh
cd server
npm install
cp .env.example .env
# Isi DATABASE_URL agar mengarah ke PostgreSQL yang berjalan, dan isi nilai rahasia.
# Isi SCHOOL_NAME, SCHOOL_CODE, ADMIN_NAME, ADMIN_EMAIL, ADMIN_PASSWORD.
npm run bootstrap-admin
```

Untuk mengimpor direktori nasional dari berkas `../data/database.js` ke PostgreSQL, jalankan `docker compose exec api node src/import-directory.js`. Importer aman dijalankan ulang dan memperbarui baris yang sudah ada. Perkiraan data saat ini sekitar 4.303 perguruan tinggi dan 34.709 program studi; periksa jumlah hasil import pada output perintah.

Untuk instalasi Docker Compose pertama, schema otomatis dijalankan dari `db/schema.sql`. Mengubah file schema setelah volume database dibuat tidak menjalankan ulang schema; buat migrasi SQL baru dan terapkan dengan prosedur backup/migrasi yang terkontrol.

## API inti

Semua endpoint selain login, health, dan pengiriman curhat memerlukan cookie sesi.

- `GET /api/health`
- `GET /api/directory/search?q=teknik&type=all&limit=25&offset=0` — pencarian alfabetis di direktori PostgreSQL
- `POST /api/auth/login` `{ "email", "password" }`
- `GET /api/auth/me`
- `POST /api/auth/logout` (sertakan `X-CSRF-Token`)
- `POST /api/auth/change-password` `{ "current_password", "new_password" }`
- `GET /api/grades` (respons sesuai peran)
- `POST /api/grades` (guru yang ditugaskan atau admin sekolah)
- `POST /api/bk/appointments` (siswa)
- `GET /api/bk/appointments` dan `PATCH /api/bk/appointments/:id/status` (BK/admin sekolah)
- `POST /api/anonymous-ventings` `{ "text", "category" }` — tanpa akun/sesi.
- `GET /api/anonymous-ventings` dan `PATCH /api/anonymous-ventings/:id/status` — hanya `wellbeing_moderator`.
- `POST /api/school/users`, `POST /api/school/classes`, `POST /api/school/teacher-assignments` — admin sekolah.
- `GET /api/school/students` — staf sekolah yang diizinkan.
- `GET/POST /api/school/alumni` — admin sekolah.

Pada frontend, gunakan `fetch('/api/...', {credentials:'include'})`. Setelah login, simpan token CSRF di memori aplikasi dan kirim sebagai header `X-CSRF-Token` untuk permintaan yang mengubah data. Jangan menyimpan sesi/token autentikasi dalam `localStorage`. Saat logout atau perubahan kata sandi, hapus token CSRF dari memori.

## Privasi curhat anonim

- Endpoint tidak membutuhkan login, tidak menautkan pengiriman dengan user ID, email, sekolah, session ID, atau user-agent.
- Teks dienkripsi dengan AES-256-GCM sebelum ditulis ke database. Kunci hanya berada di environment secret, tidak di repositori atau database.
- Tidak ada teks curhat dalam log aplikasi atau audit log. Respons moderator tidak memuat IP atau waktu kirim presisi.
- Pembatasan frekuensi berjalan di memori proses; alamat IP tidak disimpan ke tabel aplikasi. Infrastruktur hosting/reverse proxy tetap dapat memiliki log jaringan, jadi kebijakan hosting harus dikonfigurasi dan dijelaskan secara transparan.
- Karena tidak ada identitas, moderator tidak bisa menghubungi pengirim kembali. Berikan sumber bantuan yang jelas di UI dan jangan menjanjikan pemantauan real-time atau layanan darurat.
- Anonimitas tidak mutlak jika seseorang menulis nama, detail unik, atau informasi identitas dalam isi curhat. UI harus mengingatkan pengguna untuk tidak memasukkan informasi identitas.

## Pengamanan rapor

- Kata sandi di-hash dengan bcrypt (cost 12); sesi adalah token acak yang hanya disimpan dalam bentuk hash di database dan dikirim melalui cookie HttpOnly.
- Cookie memakai `SameSite=Strict`; aktifkan `COOKIE_SECURE=true` di HTTPS produksi.
- Perubahan data membutuhkan CSRF token; rate limiting login dan curhat diaktifkan.
- Nilai divalidasi 0–100; guru dibatasi pada penugasan kelas/mata pelajaran/tahun ajaran; siswa hanya melihat nilainya sendiri.
- Audit log menyimpan aksi dan referensi entitas tanpa menyalin isi rapor atau catatan konseling.
- Tetapkan backup terenkripsi, kebijakan retensi/penghapusan, prosedur insiden, rotasi rahasia, pemantauan, dan uji pemulihan sebelum produksi.

## Yang belum diselesaikan

Ini fondasi backend yang dapat dijalankan, bukan klaim bahwa layanan produksi telah dideploy atau lolos audit keamanan. UI JALUR masih perlu dihubungkan ke endpoint di atas. Belum tersedia verifikasi email, reset kata sandi mandiri, MFA untuk staf, alur undangan akun dan onboarding aman, notifikasi email/push, jadwal konseling berulang, kebijakan retensi otomatis, backup otomatis, observability produksi, atau penetration test. Buat migrasi database formal dan minta peninjauan keamanan sebelum memuat data nyata anak di bawah umur.

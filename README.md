# JALUR — Pendamping Eksplorasi Pendidikan Tinggi

## Menjalankan aplikasi
1. Ekstrak ZIP ke folder lokal.
2. Buka `JALUR/index.html` pada browser modern.
3. Direktori program studi/perguruan tinggi dimuat dari `data/database.js`.

## Jalur masuk yang tersedia
- **Siswa/Pengunjung**: fitur eksplorasi, pencarian, perbandingan, perencana biaya, jurnal, pengajuan konsultasi BK, dan catatan curhat pribadi.
- **Portal Pengelola Sekolah**: antarmuka uji untuk memasukkan/mengelola data siswa, guru, kelas, mata pelajaran, nilai rapor, dan alumni. Mendukung ekspor JSON.
- **Portal Guru BK**: antarmuka uji untuk melihat permintaan konsultasi dan mengubah status, serta melihat catatan curhat yang dibuat pada browser yang sama.

## Batas keamanan yang wajib diketahui
Versi ini adalah aplikasi statis sisi-klien. Data fitur sekolah, konsultasi, dan curhat disimpan pada `localStorage` browser. Kode akses portal pada versi ini hanyalah gerbang uji lokal, **bukan autentikasi yang aman**. Data tidak tersinkronisasi antarpengguna/perangkat dan tidak dikirim ke guru/sekolah. Jangan gunakan data pribadi siswa, nilai rapor asli, atau isi konseling yang sensitif pada versi ini.

Sebelum peluncuran resmi, implementasikan backend dan database terpusat, autentikasi server, verifikasi email/identitas sekolah, role-based access control di sisi server, kebijakan akses per siswa/guru, audit log, enkripsi saat transit dan saat tersimpan, pengelolaan sesi, perlindungan CSRF/XSS, cadangan, retensi/penghapusan data, serta prosedur penanganan insiden. Curhat anonim harus dirancang agar tidak menyimpan identitas atau metadata yang bisa mengidentifikasi pengirim; sediakan moderasi, batasan penyalahgunaan, dan protokol eskalasi keselamatan yang jelas.

## Fitur baru dalam versi ini
- Pilihan peran terpisah pada halaman pembuka.
- Formulir permintaan konsultasi BK dengan tanggal, waktu, metode, topik, catatan opsional, dan status lokal.
- Ruang curhat tanpa kolom nama, dengan pilihan suasana hati/topik, penghapusan catatan, dan peringatan privasi.
- Portal uji pengelola sekolah untuk data siswa, guru, kelas, mata pelajaran, nilai rapor, dan alumni.
- Portal uji guru BK untuk melihat permintaan konsultasi dan memperbarui status.
- Ekspor JSON data portal sekolah.

## Database direktori
Workbook sumber berada di `data/JALUR_Database_Enriched_2026-11-01.xlsx`; direktori yang digunakan aplikasi berada di `data/database.js`. Periksa tanggal dan sumber data resmi sebelum mengambil keputusan penting.


## Backend terpusat (fondasi API)
Folder `server/` berisi layanan API Node.js dan skema PostgreSQL untuk autentikasi berbasis sesi, pembatasan hak akses siswa/guru/admin sekolah/guru BK, rapor, konsultasi, alumni, serta pengiriman curhat anonim terenkripsi. Lihat `server/README.md` untuk instalasi, konfigurasi rahasia, API, dan batasan keamanan.

**Penting:** antarmuka HTML/JavaScript lama belum sepenuhnya diintegrasikan dengan API server. Sampai integrasi frontend dan pengujian produksi selesai, fitur lokal yang ada masih dapat menggunakan `localStorage`; jangan masukkan data nyata siswa/rapor/konseling. Untuk memindahkan direktori nasional ke PostgreSQL, jalankan importer yang dijelaskan di dokumentasi backend.

## Integrasi frontend + backend (mode lokal)

Frontend JALUR kini memuat `central.js` setelah `app.js`. Modul ini menghubungkan jalur masuk sekolah/BK/siswa, pencarian direktori, rapor, konsultasi BK, curhat anonim, akun sekolah, kelas, dan alumni ke API pusat. `central.js` memakai `http://localhost:8080/api` sebagai alamat API default; ubah `window.JALUR_API_BASE` sebelum `central.js` jika alamat API berbeda.

Urutan menjalankan lokal di Windows:

1. Dari `JALUR/server`, salin `.env.example` menjadi `.env`, lalu isi rahasia sesuai dokumentasi server.
2. Jalankan `docker compose up --build -d`.
3. Jalankan bootstrap administrator dan importer sesuai petunjuk di `server/README.md`.
4. Dari folder `JALUR` (folder yang berisi `index.html`), buka PowerShell dan jalankan `python -m http.server 5500 --bind 127.0.0.1`.
5. Buka `http://localhost:5500` di browser. Jangan buka `index.html` langsung dengan `file://` karena cookie/CORS tidak akan berfungsi benar.
6. Masuk melalui portal pengelola sekolah memakai akun bootstrap. Pengelola sekolah dapat membuat akun siswa/guru/BK; guru dan BK kemudian masuk melalui jalur masing-masing. Akun siswa mandiri tidak dibuat di halaman publik.

Mode lokal ini ditujukan untuk pengujian di komputer sendiri. Jangan membuka port API ke internet atau memasukkan data pendidikan nyata sebelum HTTPS, verifikasi email, pemulihan akun, backup, uji akses lintas sekolah, dan tinjauan keamanan selesai.

# Status migrasi JALUR ke Python

Tanggal pekerjaan: 2026-11-12. Status di bawah membedakan implementasi dalam source code dari hal yang membutuhkan environment/integrasi lebih lanjut.

## Dikerjakan pada paket ini
- Mempertahankan seluruh frontend asli, aset, `data/database.js`, dan workbook Excel asli.
- Menghapus Node.js sebagai backend aktif dan menggantinya dengan FastAPI.
- Membuat repository direktori yang membaca format data asli `window.JALUR_DB_RAW`.
- Menyediakan pencarian PTN dan program studi dengan paginasi, pengurutan alfabetis, pencarian seluruh field sumber, dan filter provinsi/jenjang/bidang/akreditasi/status/institusi/kapasitas.
- Mempertahankan hasil pencarian detail dari record sumber, bukan menggantinya dengan data contoh.
- Menerapkan empat pilar PBO pada alur pencarian yang dipanggil endpoint.
- Menambahkan endpoint login/logout/session dan Journal server-side per pengguna.
- Memperbaiki ukuran, padding, line-height, focus state, dan responsivitas textbox Journal.
- Menambahkan migration, konfigurasi, dokumentasi, dan automated tests untuk repository pencarian.

## Belum selesai / memerlukan konfigurasi
- Login memerlukan PostgreSQL, schema migration, akun administrator, dan secret valid.
- Endpoint terpusat `grades`, `bk/appointments`, `anonymous-ventings`, dan `school/*` belum dipindahkan. Request ke path tersebut akan memberi HTTP 501 secara eksplisit; jangan menganggap fitur portal server sudah aktif.
- Portal sekolah/BK frontend asli memiliki alur API yang sebelumnya ditujukan ke backend Node. Bagian tersebut belum sepenuhnya kompatibel dengan API Python.
- Curhat anonim terenkripsi, konsultasi BK, pengelolaan akun sekolah, rapor, alumni terpusat, dan role-based workflows belum dipindahkan.
- Guest exploration dan beberapa alat keputusan tetap menyimpan state di browser seperti versi asli.
- Journal guest tetap tersimpan lokal; Journal pengguna yang memiliki sesi server disimpan melalui `/api/journal`.
- Belum dilakukan pengujian browser end-to-end, pengujian beban, pengujian keamanan, build/deploy Vercel, maupun deployment backend.
- Database workbook bukan database transaksional aplikasi; data direktori disajikan dari snapshot `database.js`. PostgreSQL schema untuk direktori tetap tersedia untuk impor/migrasi berikutnya.

## Hasil pengujian yang diharapkan
Tes unit repository memverifikasi jumlah record, pencarian, filter, dan paginasi. Tes integrasi autentikasi/Journal memerlukan PostgreSQL dan belum dapat dinyatakan lulus tanpa konfigurasi database.

## Risiko penting
Source asli secara eksplisit menyatakan portal lokal awal bukan autentikasi aman dan data lokal tidak tersinkronisasi. Jangan mengoperasikan fitur siswa/konseling dengan data riil sampai endpoint yang belum dimigrasikan selesai, seluruh kontrol akses diverifikasi, dan uji keamanan dilakukan.

## Integrasi nilai dan ruang siswa (2026-11-12)
- Menambahkan endpoint `/api/grades`, `/api/grades/roster`, POST/PATCH/DELETE grade dengan pembatasan sekolah dan penugasan guru.
- Nilai siswa hanya dapat dibaca oleh akun siswa pemiliknya; guru dibatasi ke penugasan kelas/mata pelajaran; pengelola sekolah dibatasi ke sekolahnya.
- Menambahkan tabel `student_workspaces` untuk sinkronisasi profil akademik dan catatan eksplorasi siswa yang login.
- Menambahkan indikator navigasi aktif untuk halaman server-rendered, termasuk Jurnal Keputusan dan Konsultasi BK.
- Grafik nilai di portal server menggunakan nilai tersimpan; ringkasan dan rapor dapat dicetak atau disimpan sebagai PDF melalui dialog cetak browser.
- Status verifikasi informasi sumber ditampilkan sebagai hal yang harus diperiksa pengguna; sistem tidak mengklaim kurikulum/biaya sudah diverifikasi otomatis.
- Migration Supabase diterapkan pada project Production; RLS aktif dan akses langsung ke tabel ruang siswa dicabut dari role API publik. API hanya mengakses lewat backend.
- Belum dapat dinyatakan lulus production sebelum deployment runtime Python, browser E2E, dan uji akses lintas peran selesai.

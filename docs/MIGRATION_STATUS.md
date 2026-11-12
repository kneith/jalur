# Status migrasi JALUR ke Python

Tanggal pembaruan: 2026-11-12. Status ini membedakan endpoint yang tersedia di source dari integrasi yang sudah diuji di Production.

## Sudah tersedia pada branch `migration/python-fastapi`
- Frontend asli, aset, `backend/data/database.js`, dan dataset direktori dipertahankan.
- Backend FastAPI menyediakan health check, pencarian direktori, login/logout/session, jurnal keputusan per pengguna, dan sinkronisasi ruang kerja siswa.
- Endpoint nilai mendukung roster, baca, buat/perbarui, dan hapus nilai dengan pembatasan peran, sekolah, serta penugasan guru.
- Endpoint sekolah menyediakan pembuatan akun siswa/guru/BK, daftar siswa, daftar dan pembuatan kelas, serta daftar dan pembuatan alumni.
- Endpoint BK menyediakan permintaan konsultasi, daftar konsultasi untuk peran berwenang, dan pembaruan status.
- Curhat anonim disimpan terenkripsi; akses moderasi dibatasi ke peran moderator.
- Tabel sensitif menggunakan RLS dan akses langsung API publik dicabut; backend memakai koneksi database server-side.
- Halaman perbandingan, Plan B, Realitas Perkuliahan, pertanyaan kampus, jurnal, konsultasi, curhat, dan alumni menggunakan pilihan terstruktur. Tidak ada elemen `<textarea>` di `app.js` atau `central.js`.
- Grafik perkembangan nilai pada portal server dibuat dari data nilai yang tersimpan; ringkasan dapat dicetak melalui dialog cetak browser.

## Batasan yang masih berlaku
- Pengunjung tanpa login menyimpan sebagian besar data eksplorasi secara lokal di browser.
- Input identitas, email, pencarian, dan angka tetap memakai kontrol input satu baris yang diperlukan; larangan textbox bebas berlaku pada kolom tulisan multi-baris.
- Kurikulum, biaya kampus, dan pengalaman alumni tidak otomatis diverifikasi oleh sistem. Pengguna perlu memeriksa sumber resmi.
- Curhat anonim bukan layanan darurat dan tidak menyediakan pemantauan waktu nyata.
- Belum ada klaim bahwa uji keamanan independen, beban tinggi, atau browser end-to-end seluruh peran telah lulus.

## Database dan keamanan
- Migrasi Production yang tercatat mencakup ruang kerja siswa, indeks nilai, dan penyimpanan jurnal keputusan.
- RLS aktif pada tabel aplikasi; akses publik langsung ke tabel ruang kerja/jurnal dibatasi.
- API menggunakan session cookie dan token CSRF untuk operasi yang mengubah data; endpoint terikat peran memeriksa otorisasi di server.
- Jangan mengoperasikan fitur siswa/konseling dengan data riil sebelum uji autentikasi, pembatasan lintas-sekolah, konfigurasi secret, dan pemantauan Production diverifikasi.

## Status pengujian
- Pemeriksaan sintaks JavaScript dan kompilasi Python lokal pada sandbox telah berjalan.
- Health API Production sebelumnya merespons HTTP 200 dengan database connected dan direktori 4.303 institusi / 34.709 program studi.
- Perubahan branch harus melewati build Vercel dan pengujian endpoint setelah deployment terbaru sebelum dirilis.
- Akses otomatis ke preview yang dilindungi SSO tidak tersedia pada sesi debug ini; proteksi deployment tidak dinonaktifkan.

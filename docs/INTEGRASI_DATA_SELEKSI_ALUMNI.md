# Integrasi Data Alumni, SNBP, dan SNBT

## Data yang dimuat
- **Alumni:** seluruh 252 baris siswa pada `REKAP OUTPUT 26 FIX.xlsx`. Nama, kelas, program studi, perguruan tinggi, serta jalur/status ditampilkan. Nilai kosong ditandai sebagai “Belum diisi”; kolom NIS tidak disajikan. Data asli mempertahankan kapitalisasi jalur, sementara ringkasan menggabungkan variasi kapitalisasi status yang sama.
- **SNBT:** seluruh 4.643 kode unik dari `823331559-PASSING-GRADE-PTN-2024-2025-1.pdf`, yaitu 3.864 S1, 584 D-III, dan 195 D-IV. Tidak ada S2/S3 atau program pendidikan kedinasan pada himpunan data yang dimuat.
- **SNBP:** angka kuota dan daya tampung, tren partisipasi 2024–2026, pendaftar per jenis sekolah, pendaftar/hasil seleksi PTN akademik dan vokasi, penerimaan KIP Kuliah, 10 PTN teratas per kategori, 20 program/unit teratas, portal utama, serta 42 tautan mirror dari `Paparan Hasil SNBP 2026.pdf` (presentasi 22 halaman).
- Halaman 2–17 presentasi memuat tabel/angka kuantitatif. Halaman 18–21 berisi contoh tampilan pengumuman dan halaman 22 kredit gambar; tidak dihitung sebagai tabel statistik tambahan.

## Penempatan di aplikasi
- **Data Alumni:** tabel seluruh data, pencarian nama/program/kampus/jalur, filter kelas dan jalur/status, paginasi 30 baris per halaman, serta ringkasan distribusi.
- **Prediksi Pembanding SNBT:** pencarian katalog historis, filter jenjang, input skor UTBK, dan perbandingan selisih terhadap nilai P. Grade. Detail program studi menampilkan baris SNBT jika cocok berdasarkan kode, atau nama dan perguruan tinggi.
- **Data SNBP:** statistik nasional dan tautan pengumuman. Portal resmi utama disajikan terpisah dari 42 mirror. Detail program studi menampilkan data khusus SNBP hanya ketika nama dan perguruan tinggi cocok persis dengan salah satu baris top-program pada presentasi.

## Interpretasi dan batasan
- **P. Grade** di PDF SNBT adalah angka referensi pihak ketiga, bukan passing grade resmi SNPMB, bukan skor minimum terverifikasi, dan tidak mendukung perhitungan peluang kelulusan individual. Perbandingan hanya menunjukkan jarak skor terhadap angka referensi.
- Presentasi SNBP menyediakan statistik agregat dan daftar 10 program/unit teratas untuk masing-masing kategori akademik dan vokasi, bukan data penerimaan lengkap seluruh prodi. JALUR tidak membuat prediksi SNBP.
- Beberapa baris top SNBP dapat berupa fakultas/sekolah atau unit, bukan nama prodi reguler. Pencocokan detail memakai nama dan perguruan tinggi; jika tidak cocok, data khusus prodi tidak ditampilkan dan halaman pencarian direktori menjadi fallback.
- Angka historis tidak menjamin kapasitas, peminat, kebijakan, maupun hasil seleksi tahun berikutnya.
- Dataset dikemas sebagai gzip/Base64, dimuat secara lazy saat halaman data dibuka, dan diverifikasi jumlah serta jenjangnya sebelum dipakai. Berkasnya dimasukkan ke daftar aset statis Vercel dan diberi tipe konten teks.

## Sumber
1. `REKAP OUTPUT 26 FIX.xlsx` — lembar rekap alumni sekolah.
2. `823331559-PASSING-GRADE-PTN-2024-2025-1.pdf` — Daftar PTN UTBK-SNBT 2025, referensi pihak ketiga.
3. `Paparan Hasil SNBP 2026.pdf` — Panitia SNPMB, dipaparkan 31 Maret 2026.
# Integrasi Data Alumni, SNBP, dan SNBT

## Data yang dimuat
- **Alumni:** seluruh 252 baris pada `REKAP OUTPUT 26 FIX.xlsx`. Kolom NIS sengaja tidak disajikan. Kolom nama, kelas, prodi, perguruan tinggi, dan jalur ditampilkan; isian kosong diberi label.
- **SNBT:** seluruh 4.643 baris yang tercantum pada `Daftar PTN UTBK-SNBT 2025` (PDF referensi pihak ketiga), mencakup S1 (3.864), D-III (584), dan D-IV (195). S2/S3 dan kategori kedinasan/militer/polisi tidak dimasukkan. Karena dokumen sumber adalah daftar UTBK-SNBT, baris yang dimuat merupakan referensi program pada jalur SNBT.
- **SNBP:** tabel dan angka utama dari slide 2–17 `Paparan Hasil SNBP 2026`, termasuk kuota, daya tampung, data partisipasi 2024–2026, jenis sekolah, pendaftar dan hasil seleksi PTN akademik/vokasi, daftar PTN teratas, daftar program teratas, dan tautan mirror pengumuman.

## Interpretasi dan batasan
- Angka P. Grade di PDF SNBT berasal dari pihak ketiga. Ini bukan passing grade resmi SNPMB, bukan ambang kelulusan resmi, dan bukan probabilitas diterima. Pembanding hanya menunjukkan selisih skor terhadap referensi tersebut.
- Presentasi SNBP menyediakan statistik agregat dan daftar 10 program teratas per kategori; dokumen tersebut tidak menyediakan passing grade atau data peluang individual. Karena itu halaman SNBP adalah statistik, bukan prediksi.
- Tombol detail pada daftar program SNBP/SNBT akan mencari nama program pada direktori JALUR. Bila nama unit pada presentasi berbeda dari nama resmi prodi di direktori, halaman pencarian direktori akan dibuka sebagai fallback.
- Data seleksi bersifat historis dan tidak menjamin kapasitas, peminat, kebijakan, maupun hasil seleksi tahun mendatang.

## Implementasi
Dataset disimpan sebagai arsip gzip Base64 pada `data/admissions/admissions-data.b64` dan dimuat pada halaman data terkait. Validasi runtime memeriksa jumlah alumni (252) dan baris SNBT (4.643) sebelum data ditampilkan.

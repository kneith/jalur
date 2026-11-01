# Basis Data JALUR

Folder ini memuat:
- `database.js`: subset operasional yang dibaca antarmuka JALUR, dibuat dari workbook yang diberikan pengguna.
- `JALUR_Database_Enriched_2026-11-01.xlsx`: workbook sumber lengkap dengan seluruh lembar aslinya.

## Cakupan data terintegrasi
- 4.303 baris data perguruan tinggi.
- 34.709 baris data program studi.
- Informasi akreditasi, lokasi, status, tahun referensi, tautan sumber, dan metadata program studi yang tersedia.
- Data SNBT 2026, status estimasi skor, profil bobot simulasi, catatan metodologi, statistik nasional, sumber riset, katalog jalur, dan disclaimer.

## Batasan penting
- Dataset tidak memuat skor penerimaan per program studi yang tervalidasi. Skor kosong tidak berarti nol.
- Profil bobot subtes adalah simulasi metodologis, bukan rumus resmi SNPMB.
- Kode program studi dapat berulang di beberapa institusi. Antarmuka memakai ID baris internal agar tiap baris dapat dibuka dan dibandingkan tanpa menghapus duplikasi sumber.
- Status akreditasi dan status operasional harus diverifikasi pada sumber resmi terbaru.
- Data disertakan sebagai snapshot dan tidak diperbarui otomatis. Tautan eksternal membuka sumber asli; aplikasi tidak mengklaim telah melakukan sinkronisasi otomatis dari seluruh sumber.
- Workbook asli disimpan utuh agar seluruh lembar, termasuk audit, kamus data, data historis, dan laporan kualitas, tetap tersedia.

Untuk memeriksa dataset secara lengkap, buka workbook menggunakan Microsoft Excel, LibreOffice Calc, atau aplikasi spreadsheet yang mendukung format `.xlsx`.

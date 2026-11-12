# Laporan pengujian paket JALUR

Pengujian dilakukan pada source hasil migrasi di workspace ini, 12 November 2026.

## Berhasil dijalankan
| Pemeriksaan | Hasil | Keterangan |
|---|---|---|
| Python compileall | Lulus | `backend/app` dan `backend/scripts` berhasil dikompilasi |
| Automated repository tests | 5/5 lulus | Dataset count, pencarian institusi, pencarian program, filter/paginasi, dan polymorphic strategy |
| JavaScript syntax `app.js` | Lulus | `node --check app.js` |
| JavaScript syntax `central.js` | Lulus | `node --check central.js` |
| Dataset integrity | Lulus | Repository membaca 4.303 institusi dan 34.709 program studi dari database.js |
| ZIP integrity | Harus diverifikasi setelah paket dibangun | Arsip final diuji dengan `ZipFile.testzip()` |

## Belum diuji
- Menyalakan FastAPI dengan seluruh dependency terpasang.
- Koneksi PostgreSQL, migration SQL, bootstrap admin, dan import dataset ke PostgreSQL.
- Alur login/logout/CSRF dengan database nyata.
- Journal server-side melalui browser.
- Endpoint portal sekolah/BK yang belum dimigrasikan.
- Browser end-to-end guest vs login, responsivitas visual, dan uji beban Journal.
- Build/deployment Vercel dan hosting backend.
- Security review dan pengujian akses lintas sekolah.

## Kendala lingkungan
Dependency Python tambahan tidak dapat diunduh pada sesi pengerjaan ini karena akses jaringan paket tidak tersedia. Karena itu, unit tests repository dan pemeriksaan sintaks berhasil, tetapi server FastAPI dan koneksi PostgreSQL tidak dijalankan. Hasil ini tidak boleh ditafsirkan sebagai pengujian integrasi lulus.

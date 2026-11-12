# Laporan pengujian paket JALUR

Pembaruan: 12 November 2026. Laporan ini membedakan hasil uji baseline yang pernah dijalankan dari pemeriksaan source terbaru.

## Hasil uji baseline yang pernah dijalankan
| Pemeriksaan | Hasil | Keterangan |
|---|---|---|
| Python compileall | Lulus pada baseline sebelumnya | `backend/app` dan `backend/scripts` |
| Automated repository tests | 5/5 lulus pada baseline sebelumnya | Dataset count, pencarian institusi, pencarian program, filter/paginasi, dan polymorphic strategy |
| JavaScript syntax `app.js` | Lulus pada baseline sebelumnya | `node --check app.js` |
| JavaScript syntax `central.js` | Lulus pada baseline sebelumnya | `node --check central.js` |
| Dataset integrity | Lulus pada baseline sebelumnya | 4.303 institusi dan 34.709 program studi |

## Pemeriksaan source terbaru
- Tidak ditemukan elemen `<textarea>` di `app.js` maupun `central.js`.
- Halaman Realitas Perkuliahan dan Daftar Pertanyaan untuk Kampus menggunakan pilihan terstruktur.
- Source menyediakan endpoint workspace siswa, jurnal, nilai, konsultasi BK, curhat anonim, kelas sekolah, alumni, serta penugasan guru.
- Pembuatan akun siswa mewajibkan kelas dan NIS; penugasan guru dibatasi sekolah, kelas, guru, mata pelajaran, dan tahun ajaran.
- Token CSRF dibuat stabil per sesi untuk menghindari invalidasi antar-tab.
- Workflow GitHub Actions `jalur-quality.yml` ditambahkan untuk menjalankan compileall, pytest, pemeriksaan sintaks JavaScript, dan pemeriksaan textarea. Belum ada hasil run yang dapat diverifikasi pada saat laporan ini diperbarui.

## Belum terverifikasi pada source terbaru
- Build Vercel untuk commit terbaru dan pengujian endpoint dari deployment tersebut.
- Login/logout/CSRF dengan browser nyata dan cookie lintas subdomain.
- CRUD jurnal, ruang siswa, kelas, penugasan guru, dan nilai melalui browser dengan akun uji tiap role.
- Uji akses lintas sekolah dan penolakan akses lintas peran.
- Alur konsultasi BK dan moderasi curhat anonim end-to-end.
- Uji browser responsif, beban, pemulihan sesi, dan security review independen.

## Kendala pengujian saat ini
- Preview Vercel menggunakan SSO protection; fetch otomatis pada sesi ini tidak dapat melewati halaman autentikasi, dan proteksi tidak dinonaktifkan.
- Vercel menolak pembuatan deployment tambahan karena batas API deployment harian pada plan saat ini (minta coba lagi dalam 24 jam).
- Karena itu, status `READY` pada deployment lama tidak membuktikan bahwa commit terbaru telah terpasang atau fitur end-to-end telah lulus.

**Keputusan rilis:** jangan promosikan ke Production sebelum preview dari commit terbaru berhasil dibangun dan tes endpoint serta role selesai.

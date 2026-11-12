# Penerapan empat pilar PBO

Empat pilar diterapkan pada jalur pencarian direktori yang benar-benar dipanggil oleh endpoint `/api/directory/search`.

## Abstraction
`backend/app/repositories/directory.py` mendefinisikan `SearchStrategy` dan `DirectoryRepository` sebagai abstract base class (`abc.ABC`) dengan `@abstractmethod`. Service tidak bergantung pada detail pemuatan file.

## Inheritance
`ContainsStrategy` dan `ExactStrategy` mewarisi `SearchStrategy`. `JSONDirectoryRepository` mewarisi `DirectoryRepository`. `InstitutionDirectoryService` dan `ProgramDirectoryService` mewarisi `DirectoryService` untuk mengkhususkan tipe sumber daya.

## Polymorphism
`DirectoryService.search()` menerima objek `SearchStrategy` dan memanggil kontrak `matches()`. `ContainsStrategy` dan `ExactStrategy` mengimplementasikan perilaku pencocokan berbeda. Pemilihan strategi terjadi pada setiap pemanggilan service berdasarkan parameter `exact`.

## Encapsulation
`JSONDirectoryRepository` menyimpan path, koleksi, dan indeks pencarian dalam atribut private (`__source_path`, `__institutions`, `__programs`, `__institution_index`, `__program_index`). Data dibuka melalui method `search()` dan ringkasan jumlah melalui property read-only `counts`.

## Alur integrasi
`GET /api/directory/search` → `DirectoryService.search()` → `JSONDirectoryRepository.search()` → strategi `SearchStrategy.matches()` → hasil paginasi dan data sumber lengkap.

## Catatan
Ini adalah penerapan PBO yang digunakan langsung oleh pencarian. Abstraksi repository juga memungkinkan implementasi PostgreSQL baru tanpa mengubah kontrak service. Saat ini implementasi aktif adalah snapshot JSON sumber asli; tabel direktori PostgreSQL dari skema lama disediakan untuk migrasi lanjutan.

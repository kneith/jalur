"""Create a platform administrator interactively; never stores plaintext credentials."""
import getpass, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.core.database import connection
from app.core.security import hash_password

email = input("Admin email: ").strip().lower()
name = input("Nama lengkap: ").strip()
password = getpass.getpass("Password (minimal 14 karakter): ")
if len(password) < 14:
    raise SystemExit("Password harus minimal 14 karakter.")
if not settings.database_url:
    raise SystemExit("DATABASE_URL belum dikonfigurasi pada backend/.env")
with connection() as conn:
    conn.execute("""INSERT INTO users(school_id,email,full_name,password_hash,role,status)
                    VALUES(NULL,%s,%s,%s,'platform_admin','active')""",
                 (email,name,hash_password(password)))
print("Admin platform berhasil dibuat. Simpan kredensial dengan aman.")

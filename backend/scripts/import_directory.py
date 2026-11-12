"""Import the unchanged original directory snapshot into PostgreSQL."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psycopg.types.json import Jsonb
from app.core.config import settings
from app.core.database import connection

source = Path(settings.directory_data_path)
raw = source.read_text(encoding="utf-8")
marker = "window.JALUR_DB_RAW="
start = raw.find(marker)
if start < 0:
    raise SystemExit("database.js tidak berisi window.JALUR_DB_RAW.")
data = json.loads(raw[start + len(marker):].strip().rstrip(";"))
institutions = [dict(zip(data["ik"], row)) for row in data["i"]]
programs = [dict(zip(data["pk"], row)) for row in data["p"]]

def search_text(row):
    return " ".join(str(v) for v in row.values() if v is not None)

with connection() as conn:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE directory_programs, directory_institutions")
        inst_rows = [
            (str(row.get("id") or row.get("name")), str(row.get("name") or "Nama tidak tersedia"),
             search_text(row), Jsonb(row))
            for row in institutions
        ]
        cur.executemany("""INSERT INTO directory_institutions(id,name,search_text,data)
                           VALUES(%s,%s,%s,%s)""", inst_rows)
        program_rows = [
            (str(row.get("id")), str(row.get("institutionId")) if row.get("institutionId") is not None else None,
             str(row.get("name") or "Nama tidak tersedia"), str(row.get("campus") or ""),
             str(row.get("level")) if row.get("level") is not None else None,
             str(row.get("field")) if row.get("field") is not None else None,
             search_text(row), Jsonb(row))
            for row in programs
        ]
        cur.executemany("""INSERT INTO directory_programs
            (id,institution_id,name,institution_name,level,field,search_text,data)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", program_rows)
print(f"Imported {len(institutions):,} institutions and {len(programs):,} programs.")

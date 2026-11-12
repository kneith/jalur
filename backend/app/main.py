"""JALUR Python API — FastAPI migration from the original Node backend."""
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from time import monotonic
import secrets, uuid
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from app.core.config import settings
from app.core.database import connection, close_pool
from app.core.security import digest, new_token, verify_password
from app.repositories.directory import JSONDirectoryRepository
from app.repositories.postgres_directory import PostgresDirectoryRepository
from app.services import DirectoryService
import os

if settings.database_url and len(settings.session_pepper) < 32:
    raise RuntimeError("SESSION_PEPPER harus berisi minimal 32 karakter.")
if os.getenv("DIRECTORY_BACKEND", "json").lower() == "postgres" and settings.database_url:
    repository = PostgresDirectoryRepository(connection)
else:
    repository = JSONDirectoryRepository(settings.directory_data_path)
directory_service = DirectoryService(repository)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_pool()

app = FastAPI(title="JALUR API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                   allow_credentials=True, allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"],
                   allow_headers=["Content-Type","X-CSRF-Token"])

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

_login_attempts = defaultdict(deque)

class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)

class JournalInput(BaseModel):
    type: str = Field(min_length=1, max_length=80)
    program: str | None = Field(default=None, max_length=240)
    text: str = Field(min_length=3, max_length=12000)

def current_user(request: Request, required: bool = True):
    token = request.cookies.get("jalur_session")
    if not token:
        if required: raise HTTPException(401, "Sesi tidak aktif.")
        return None
    try:
        with connection() as conn:
            row = conn.execute("""
                SELECT s.id AS session_id, s.csrf_hash, s.expires_at,
                       u.id, u.school_id, u.email, u.full_name, u.role, u.status,
                       sc.status AS school_status
                FROM sessions s JOIN users u ON u.id=s.user_id
                LEFT JOIN schools sc ON sc.id=u.school_id
                WHERE s.token_hash=%s AND s.expires_at>now()
            """, (digest(token),)).fetchone()
    except RuntimeError:
        raise HTTPException(503, "Database belum dikonfigurasi.")
    if not row or row["status"] != "active" or (row["school_id"] and row["school_status"] != "active"):
        if required: raise HTTPException(401, "Sesi tidak aktif.")
        return None
    if request.method not in ("GET","HEAD","OPTIONS"):
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or not secrets.compare_digest(digest(csrf), row["csrf_hash"]):
            raise HTTPException(403, "Token CSRF tidak valid.")
    return row

@app.get("/api/health")
def health():
    result = {"ok": True, "service": "jalur-python-api"}
    if hasattr(repository, "counts"):
        result["directory"] = repository.counts
    try:
        with connection() as conn: conn.execute("SELECT 1")
        result["database"] = "connected"
    except RuntimeError:
        result["database"] = "not_configured"
    except Exception:
        result["database"] = "unavailable"
    return result

@app.get("/api/directory/search")
def search_directory(q: str = Query("", max_length=120),
                     type: str = Query("all", pattern="^(all|institution|program)$"),
                     limit: int = Query(25, ge=1, le=100),
                     offset: int = Query(0, ge=0),
                     province: str | None = None, level: str | None = None,
                     field: str | None = None, accreditation: str | None = None,
                     status: str | None = None, institution: str | None = None,
                     capacity_min: float | None = Query(None, ge=0),
                     capacity_max: float | None = Query(None, ge=0),
                     exact: bool = False):
    if not q.strip(): return {"items": [], "total": 0, "limit": limit, "offset": offset}
    filters = {"province":province, "level":level, "field":field, "accreditation":accreditation,
               "status":status, "institution":institution, "capacity_min":capacity_min, "capacity_max":capacity_max}
    items, total = directory_service.search(q.strip(), type, limit, offset, filters, exact)
    return {"items":items, "total":total, "limit":limit, "offset":offset, "alphabetical":True}

@app.post("/api/auth/login")
def login(payload: LoginInput, response: Response, request: Request):
    ip = request.client.host if request.client else "unknown"
    now = monotonic()
    attempts = _login_attempts[ip]
    while attempts and now - attempts[0] > 900:
        attempts.popleft()
    if len(attempts) >= 10:
        raise HTTPException(429, "Terlalu banyak percobaan login. Coba lagi 15 menit lagi.")
    attempts.append(now)
    email = str(payload.email).strip().lower()
    try:
        with connection() as conn:
            user = conn.execute("""
                SELECT u.id,u.school_id,u.email,u.full_name,u.password_hash,u.role,u.status,
                       s.status AS school_status
                FROM users u LEFT JOIN schools s ON s.id=u.school_id
                WHERE lower(u.email)=lower(%s) LIMIT 1
            """, (email,)).fetchone()
            if (not user or not verify_password(payload.password, user["password_hash"])
                or user["status"] != "active"
                or (user["school_id"] and user["school_status"] != "active")):
                raise HTTPException(401, "Email atau kata sandi tidak sesuai.")
            session_token, csrf = new_token(32), new_token(24)
            conn.execute("""INSERT INTO sessions(user_id,token_hash,csrf_hash,expires_at)
                            VALUES(%s,%s,%s,now()+(%s * interval '1 hour'))""",
                         (user["id"], digest(session_token), digest(csrf), settings.session_ttl_hours))
            _login_attempts.pop(ip, None)
    except RuntimeError:
        raise HTTPException(503, "Database belum dikonfigurasi.")
    opts = {"max_age": settings.session_ttl_hours*3600, "secure": settings.cookie_secure,
            "samesite": "none" if settings.cookie_secure else "lax"}
    response.set_cookie("jalur_session", session_token, httponly=True, path="/api", **opts)
    response.set_cookie("jalur_csrf", csrf, httponly=False, path="/", **opts)
    return {"user": {k:user[k] for k in ("id","school_id","full_name","email","role")}, "csrfToken":csrf}

@app.get("/api/auth/me")
def me(request: Request):
    user = current_user(request)
    return {"user": {k:user[k] for k in ("id","school_id","full_name","email","role")}}

@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    user = current_user(request)
    with connection() as conn: conn.execute("DELETE FROM sessions WHERE id=%s", (user["session_id"],))
    response.delete_cookie("jalur_session", path="/api", secure=settings.cookie_secure,
                           samesite="none" if settings.cookie_secure else "lax")
    response.delete_cookie("jalur_csrf", path="/", secure=settings.cookie_secure,
                           samesite="none" if settings.cookie_secure else "lax")

@app.get("/api/journal")
def get_journal(request: Request):
    user = current_user(request)
    with connection() as conn:
        rows = conn.execute("""SELECT id,entry_type AS type,program_name AS program,content AS text,
                               to_char(created_at AT TIME ZONE 'Asia/Jakarta','DD Mon YYYY HH24:MI') AS date
                               FROM decision_journal WHERE user_id=%s ORDER BY created_at DESC LIMIT 200""",
                            (user["id"],)).fetchall()
    return {"items":[dict(r) for r in rows]}

@app.post("/api/journal", status_code=201)
def create_journal(payload: JournalInput, request: Request):
    user = current_user(request)
    with connection() as conn:
        row = conn.execute("""INSERT INTO decision_journal(user_id,entry_type,program_name,content)
                              VALUES(%s,%s,%s,%s) RETURNING id""",
                           (user["id"],payload.type,payload.program,payload.text)).fetchone()
    return {"id":row["id"], "saved":True}

@app.delete("/api/journal/{entry_id}", status_code=204)
def delete_journal(entry_id: uuid.UUID, request: Request):
    user = current_user(request)
    with connection() as conn:
        result = conn.execute("DELETE FROM decision_journal WHERE id=%s AND user_id=%s",
                              (entry_id,user["id"]))
        if result.rowcount == 0: raise HTTPException(404, "Catatan tidak ditemukan.")

# Legacy API paths that are intentionally explicit rather than silently pretending to work.
@app.get("/api/{path:path}")
def unimplemented_get(path: str):
    if path.startswith(("grades","bk/","school/","anonymous-ventings")):
        raise HTTPException(501, "Endpoint ini belum dimigrasikan ke Python. Lihat docs/MIGRATION_STATUS.md.")
    raise HTTPException(404, "Endpoint tidak ditemukan.")


@app.api_route("/api/{path:path}", methods=["POST", "PATCH", "PUT", "DELETE"])
def unimplemented_write(path: str):
    raise HTTPException(501, "Endpoint ini belum dimigrasikan ke Python. Lihat docs/MIGRATION_STATUS.md.")

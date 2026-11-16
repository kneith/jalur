"""JALUR Python API — FastAPI migration from the original Node backend."""
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from time import monotonic, sleep
import secrets, uuid
import base64
from datetime import datetime
from typing import Literal, Any
import json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, EmailStr, Field
from app.core.config import settings
from app.core.database import connection, close_pool
from app.core.security import digest, new_token, verify_password, hash_password
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

app = FastAPI(title="JALUR API", version="2.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                   allow_credentials=True, allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"],
                   allow_headers=["Content-Type","X-CSRF-Token","X-RASA-ACCESS-CODE"])


@app.exception_handler(PoolTimeout)
async def database_pool_timeout_handler(request: Request, exc: PoolTimeout):
    # Pool exhaustion is transient; return a retryable response instead of 500.
    return JSONResponse(
        status_code=503,
        content={"detail": "Layanan database sedang sibuk. Silakan coba lagi."},
        headers={"Retry-After": "3"},
    )


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


class GradeInput(BaseModel):
    student_id: uuid.UUID
    class_id: uuid.UUID
    subject_name: str = Field(min_length=1, max_length=120)
    semester: str = Field(min_length=1, max_length=30)
    academic_year: str = Field(min_length=4, max_length=20)
    score: float = Field(ge=0, le=100)
    notes: str | None = Field(default=None, max_length=1000)


class StudentWorkspaceInput(BaseModel):
    workspace: dict[str, Any]

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
        result["ok"] = False
        result["database"] = "not_configured"
        return JSONResponse(status_code=503, content=result)
    except Exception:
        result["ok"] = False
        result["database"] = "unavailable"
        return JSONResponse(status_code=503, content=result)
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
            session_token = new_token(32)
            session = conn.execute(
                """INSERT INTO sessions(user_id,token_hash,csrf_hash,expires_at)
                   VALUES(%s,%s,%s,now()+(%s * interval '1 hour'))
                   RETURNING id""",
                (user["id"], digest(session_token), "pending", settings.session_ttl_hours),
            ).fetchone()
            # Stable, session-bound CSRF token: all tabs for this session share
            # the same value without exposing a parent-domain cookie.
            csrf = digest(f"csrf:{session['id']}:{user['id']}")
            conn.execute("UPDATE sessions SET csrf_hash=%s WHERE id=%s", (digest(csrf), session["id"]))
            _login_attempts.pop(ip, None)
    except RuntimeError:
        raise HTTPException(503, "Database belum dikonfigurasi.")
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    secure_cookie = settings.cookie_secure or forwarded_proto == "https" or request.url.scheme == "https"
    opts = {"max_age": settings.session_ttl_hours*3600, "secure": secure_cookie,
            "samesite": "none" if secure_cookie else "lax"}
    response.set_cookie("jalur_session", session_token, httponly=True, path="/api", **opts)
    response.set_cookie("jalur_csrf", csrf, httponly=False, path="/", **opts)
    return {"user": {k:user[k] for k in ("id","school_id","full_name","email","role")}, "csrfToken":csrf}

@app.get("/api/auth/me")
def me(request: Request):
    user = current_user(request)
    # Deterministic per-session token avoids invalidating another open tab.
    csrf = digest(f"csrf:{user['session_id']}:{user['id']}")
    return {
        "user": {k:user[k] for k in ("id","school_id","full_name","email","role")},
        "csrfToken": csrf,
    }

@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    user = current_user(request)
    with connection() as conn: conn.execute("DELETE FROM sessions WHERE id=%s", (user["session_id"],))
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    secure_cookie = settings.cookie_secure or forwarded_proto == "https" or request.url.scheme == "https"
    same_site = "none" if secure_cookie else "lax"
    response.delete_cookie("jalur_session", path="/api", secure=secure_cookie, samesite=same_site)
    response.delete_cookie("jalur_csrf", path="/", secure=secure_cookie, samesite=same_site)

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

# ---------------------------------------------------------------------------
# Student-owned workspace and role-scoped grade records.
# These endpoints use the server's private PostgreSQL connection; no client
# receives database credentials or direct access to these tables.
# ---------------------------------------------------------------------------

WORKSPACE_KEYS = {
    "profile", "notes", "compared", "mainChoice", "alternatives",
    "checked", "costPlans", "pathwayGroups", "settings",
}


@app.get("/api/workspace")
def get_student_workspace(request: Request):
    actor = _require_roles(request, "student")
    if not actor["school_id"]:
        raise HTTPException(403, "Akun siswa belum terhubung ke sekolah.")
    with connection() as conn:
        row = conn.execute(
            """SELECT workspace_data, updated_at
               FROM student_workspaces WHERE user_id=%s AND school_id=%s""",
            (actor["id"], actor["school_id"]),
        ).fetchone()
    return {"workspace": dict(row["workspace_data"]) if row else None,
            "updated_at": row["updated_at"] if row else None}


@app.post("/api/workspace")
def save_student_workspace(payload: StudentWorkspaceInput, request: Request):
    actor = _require_roles(request, "student")
    if not actor["school_id"]:
        raise HTTPException(403, "Akun siswa belum terhubung ke sekolah.")
    workspace = {key: value for key, value in payload.workspace.items() if key in WORKSPACE_KEYS}
    try:
        encoded = json.dumps(workspace, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise HTTPException(422, "Format data profil tidak valid.")
    if len(encoded.encode("utf-8")) > 250_000:
        raise HTTPException(413, "Data ruang siswa terlalu besar untuk disimpan.")
    with connection() as conn:
        row = conn.execute(
            """INSERT INTO student_workspaces(user_id, school_id, workspace_data, updated_at)
               VALUES (%s, %s, %s::jsonb, now())
               ON CONFLICT (user_id) DO UPDATE
                 SET school_id=EXCLUDED.school_id,
                     workspace_data=EXCLUDED.workspace_data,
                     updated_at=now()
               WHERE student_workspaces.school_id=EXCLUDED.school_id
               RETURNING updated_at""",
            (actor["id"], actor["school_id"], encoded),
        ).fetchone()
    if not row:
        raise HTTPException(409, "Sekolah akun berubah. Muat ulang sesi sebelum menyimpan.")
    return {"saved": True, "updated_at": row["updated_at"]}


def _grade_teacher_id(conn, actor, payload: GradeInput):
    school_id = actor["school_id"]
    student = conn.execute(
        """SELECT u.id, sp.class_id
           FROM users u JOIN student_profiles sp ON sp.user_id=u.id
           WHERE u.id=%s AND u.school_id=%s AND u.role='student' AND u.status='active'""",
        (payload.student_id, school_id),
    ).fetchone()
    if not student:
        raise HTTPException(404, "Siswa tidak ditemukan di sekolah ini.")
    class_row = conn.execute(
        "SELECT id FROM school_classes WHERE id=%s AND school_id=%s",
        (payload.class_id, school_id),
    ).fetchone()
    if not class_row:
        raise HTTPException(404, "Kelas tidak ditemukan di sekolah ini.")
    if student["class_id"] is None:
        raise HTTPException(400, "Siswa belum ditetapkan ke kelas. Tetapkan kelas pada profil siswa terlebih dahulu.")
    if student["class_id"] != payload.class_id:
        raise HTTPException(400, "Kelas yang dipilih tidak sesuai dengan data siswa.")
    subject = payload.subject_name.strip()
    year = payload.academic_year.strip()
    if not subject or not year:
        raise HTTPException(422, "Mata pelajaran dan tahun ajaran wajib diisi.")
    if actor["role"] == "teacher":
        assignment = conn.execute(
            """SELECT 1 FROM teacher_assignments
               WHERE school_id=%s AND teacher_id=%s AND class_id=%s
                 AND lower(subject_name)=lower(%s) AND academic_year=%s""",
            (school_id, actor["id"], payload.class_id, subject, year),
        ).fetchone()
        if not assignment:
            raise HTTPException(403, "Guru tidak memiliki penugasan untuk kelas, mata pelajaran, dan tahun ajaran ini.")
        return actor["id"]
    return None


@app.get("/api/grades/roster")
def get_grade_roster(request: Request):
    actor = _require_roles(request, "teacher", "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun belum terhubung ke sekolah.")
    with connection() as conn:
        if actor["role"] == "teacher":
            classes = conn.execute(
                """SELECT DISTINCT c.id, c.name, c.academic_year
                   FROM teacher_assignments ta
                   JOIN school_classes c ON c.id=ta.class_id AND c.school_id=ta.school_id
                   WHERE ta.school_id=%s AND ta.teacher_id=%s
                   ORDER BY c.academic_year DESC, c.name""",
                (school_id, actor["id"]),
            ).fetchall()
            class_ids = [row["id"] for row in classes]
            students = conn.execute(
                """SELECT u.id, u.full_name, sp.student_number, sp.class_id,
                          c.name AS class_name
                   FROM users u
                   JOIN student_profiles sp ON sp.user_id=u.id
                   LEFT JOIN school_classes c ON c.id=sp.class_id
                   WHERE u.school_id=%s AND u.role='student' AND u.status='active'
                     AND sp.class_id = ANY(%s)
                   ORDER BY c.name, u.full_name LIMIT 1000""",
                (school_id, class_ids),
            ).fetchall() if class_ids else []
        else:
            classes = conn.execute(
                """SELECT id, name, academic_year FROM school_classes
                   WHERE school_id=%s ORDER BY academic_year DESC, name""",
                (school_id,),
            ).fetchall()
            students = conn.execute(
                """SELECT u.id, u.full_name, sp.student_number, sp.class_id,
                          c.name AS class_name
                   FROM users u
                   JOIN student_profiles sp ON sp.user_id=u.id
                   LEFT JOIN school_classes c ON c.id=sp.class_id
                   WHERE u.school_id=%s AND u.role='student' AND u.status='active'
                   ORDER BY c.name, u.full_name LIMIT 1000""",
                (school_id,),
            ).fetchall()
    return {"classes": [dict(row) for row in classes],
            "students": [dict(row) for row in students]}


@app.get("/api/grades")
def get_grades(request: Request):
    actor = _require_roles(request, "student", "teacher", "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun belum terhubung ke sekolah.")
    with connection() as conn:
        if actor["role"] == "student":
            rows = conn.execute(
                """SELECT g.id, g.student_id, g.class_id, g.subject_name, g.semester,
                          g.academic_year, g.score, g.notes, g.version, g.updated_at,
                          c.name AS class_name
                   FROM grades g LEFT JOIN school_classes c ON c.id=g.class_id
                   WHERE g.school_id=%s AND g.student_id=%s
                   ORDER BY g.academic_year, g.semester, g.subject_name""",
                (school_id, actor["id"]),
            ).fetchall()
        elif actor["role"] == "teacher":
            rows = conn.execute(
                """SELECT g.id, g.student_id, g.class_id, g.subject_name, g.semester,
                          g.academic_year, g.score, g.notes, g.version, g.updated_at,
                          u.full_name AS student_name, sp.student_number, c.name AS class_name
                   FROM grades g
                   JOIN users u ON u.id=g.student_id
                   LEFT JOIN student_profiles sp ON sp.user_id=u.id
                   LEFT JOIN school_classes c ON c.id=g.class_id
                   WHERE g.school_id=%s AND EXISTS (
                     SELECT 1 FROM teacher_assignments ta
                     WHERE ta.school_id=g.school_id AND ta.teacher_id=%s
                       AND ta.class_id=g.class_id
                       AND lower(ta.subject_name)=lower(g.subject_name)
                       AND ta.academic_year=g.academic_year
                   )
                   ORDER BY g.academic_year DESC, g.semester, c.name, u.full_name
                   LIMIT 1000""",
                (school_id, actor["id"]),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT g.id, g.student_id, g.class_id, g.subject_name, g.semester,
                          g.academic_year, g.score, g.notes, g.version, g.updated_at,
                          u.full_name AS student_name, sp.student_number, c.name AS class_name
                   FROM grades g
                   JOIN users u ON u.id=g.student_id
                   LEFT JOIN student_profiles sp ON sp.user_id=u.id
                   LEFT JOIN school_classes c ON c.id=g.class_id
                   WHERE g.school_id=%s
                   ORDER BY g.academic_year DESC, g.semester, c.name, u.full_name
                   LIMIT 2000""",
                (school_id,),
            ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/grades", status_code=201)
def upsert_grade(payload: GradeInput, request: Request):
    actor = _require_roles(request, "teacher", "school_admin")
    if not actor["school_id"]:
        raise HTTPException(403, "Akun belum terhubung ke sekolah.")
    with connection() as conn:
        teacher_id = _grade_teacher_id(conn, actor, payload)
        item = conn.execute(
            """INSERT INTO grades(school_id, student_id, teacher_id, class_id,
                                  subject_name, semester, academic_year, score, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (student_id, subject_name, semester, academic_year)
               DO UPDATE SET school_id=EXCLUDED.school_id,
                             teacher_id=EXCLUDED.teacher_id,
                             class_id=EXCLUDED.class_id,
                             score=EXCLUDED.score, notes=EXCLUDED.notes,
                             version=grades.version+1, updated_at=now()
               RETURNING id, student_id, class_id, subject_name, semester,
                         academic_year, score, notes, version, updated_at""",
            (actor["school_id"], payload.student_id, teacher_id, payload.class_id,
             payload.subject_name.strip(), payload.semester.strip(),
             payload.academic_year.strip(), payload.score,
             (payload.notes or "").strip() or None),
        ).fetchone()
        _audit_event(conn, actor, "grade.upsert", "grade", item["id"])
    return {"item": dict(item)}


@app.patch("/api/grades/{grade_id}")
def update_grade(grade_id: uuid.UUID, payload: GradeInput, request: Request):
    actor = _require_roles(request, "teacher", "school_admin")
    if not actor["school_id"]:
        raise HTTPException(403, "Akun belum terhubung ke sekolah.")
    with connection() as conn:
        teacher_id = _grade_teacher_id(conn, actor, payload)
        if actor["role"] == "teacher":
            item = conn.execute(
                """UPDATE grades g SET student_id=%s, teacher_id=%s, class_id=%s,
                          subject_name=%s, semester=%s, academic_year=%s, score=%s,
                          notes=%s, version=g.version+1, updated_at=now()
                   WHERE g.id=%s AND g.school_id=%s AND EXISTS (
                     SELECT 1 FROM teacher_assignments ta
                     WHERE ta.school_id=g.school_id AND ta.teacher_id=%s
                       AND ta.class_id=g.class_id
                       AND lower(ta.subject_name)=lower(g.subject_name)
                       AND ta.academic_year=g.academic_year
                   )
                   RETURNING g.id, g.student_id, g.class_id, g.subject_name,
                             g.semester, g.academic_year, g.score, g.notes,
                             g.version, g.updated_at""",
                (payload.student_id, teacher_id, payload.class_id,
                 payload.subject_name.strip(), payload.semester.strip(),
                 payload.academic_year.strip(), payload.score,
                 (payload.notes or "").strip() or None,
                 grade_id, actor["school_id"], actor["id"]),
            ).fetchone()
        else:
            item = conn.execute(
                """UPDATE grades SET student_id=%s, teacher_id=NULL, class_id=%s,
                          subject_name=%s, semester=%s, academic_year=%s, score=%s,
                          notes=%s, version=version+1, updated_at=now()
                   WHERE id=%s AND school_id=%s
                   RETURNING id, student_id, class_id, subject_name, semester,
                             academic_year, score, notes, version, updated_at""",
                (payload.student_id, payload.class_id, payload.subject_name.strip(),
                 payload.semester.strip(), payload.academic_year.strip(), payload.score,
                 (payload.notes or "").strip() or None, grade_id, actor["school_id"]),
            ).fetchone()
        if not item:
            raise HTTPException(404, "Nilai tidak ditemukan atau akses tidak diizinkan.")
        _audit_event(conn, actor, "grade.update", "grade", grade_id)
    return {"item": dict(item)}


@app.delete("/api/grades/{grade_id}", status_code=204)
def delete_grade(grade_id: uuid.UUID, request: Request):
    actor = _require_roles(request, "teacher", "school_admin")
    if not actor["school_id"]:
        raise HTTPException(403, "Akun belum terhubung ke sekolah.")
    with connection() as conn:
        if actor["role"] == "teacher":
            item = conn.execute(
                """DELETE FROM grades g
                   WHERE g.id=%s AND g.school_id=%s AND EXISTS (
                     SELECT 1 FROM teacher_assignments ta
                     WHERE ta.school_id=g.school_id AND ta.teacher_id=%s
                       AND ta.class_id=g.class_id
                       AND lower(ta.subject_name)=lower(g.subject_name)
                       AND ta.academic_year=g.academic_year
                   )
                   RETURNING g.id""",
                (grade_id, actor["school_id"], actor["id"]),
            ).fetchone()
        else:
            item = conn.execute(
                "DELETE FROM grades WHERE id=%s AND school_id=%s RETURNING id",
                (grade_id, actor["school_id"]),
            ).fetchone()
        if not item:
            raise HTTPException(404, "Nilai tidak ditemukan atau akses tidak diizinkan.")
        _audit_event(conn, actor, "grade.delete", "grade", grade_id)


# ---------------------------------------------------------------------------
# Migrated school, BK, platform moderator and anonymous-venting endpoints.
# All write endpoints use current_user(), which enforces session + CSRF.
# ---------------------------------------------------------------------------

class SchoolUserInput(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    role: Literal["student", "teacher", "counselor"]
    temporary_password: str = Field(min_length=14, max_length=200)
    student_number: str | None = Field(default=None, max_length=40)
    class_id: uuid.UUID | None = None
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)


class SchoolClassInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    academic_year: str = Field(min_length=4, max_length=20)


class SchoolClassUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    academic_year: str = Field(min_length=4, max_length=20)
    homeroom_teacher_id: uuid.UUID | None = None


class SchoolUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    student_number: str | None = Field(default=None, max_length=40)
    class_id: uuid.UUID | None = None
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)


class SchoolUserStatusInput(BaseModel):
    status: Literal["active", "disabled"]


class TeacherAssignmentInput(BaseModel):
    teacher_id: uuid.UUID
    class_id: uuid.UUID
    subject_name: str = Field(min_length=1, max_length=120)
    academic_year: str = Field(min_length=4, max_length=20)


class SchoolAlumniInput(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    graduation_year: int = Field(ge=1950, le=2100)
    next_step: str | None = Field(default=None, max_length=120)
    institution: str | None = Field(default=None, max_length=180)
    program: str | None = Field(default=None, max_length=180)
    consent_to_share: bool = False


class PlatformModeratorInput(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    temporary_password: str = Field(min_length=14, max_length=200)


class BKAppointmentInput(BaseModel):
    requested_at: datetime
    mode: Literal["in_person", "online"]
    topic: str = Field(min_length=1, max_length=120)
    student_note: str | None = Field(default=None, max_length=1000)


class BKAppointmentStatusInput(BaseModel):
    status: Literal["pending", "confirmed", "reschedule_requested", "completed", "cancelled"]


class AnonymousVentingInput(BaseModel):
    text: str = Field(min_length=3, max_length=3000)
    category: Literal["academic", "family", "friends", "future", "wellbeing", "other"]


class AnonymousVentingStatusInput(BaseModel):
    status: Literal["unreviewed", "reviewed", "resource_shared", "closed"]

class RasaConversationInput(BaseModel):
    text: str = Field(min_length=3, max_length=3000)
    category: Literal["academic","family","friends","future","wellbeing","other"] = "other"
    school_id: uuid.UUID | None = None
class RasaMessageInput(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    client_message_id: uuid.UUID | None = None
class RasaAccessInput(BaseModel):
    access_code: str = Field(min_length=20, max_length=100)
class RasaReviewInput(BaseModel):
    decision: Literal["awaiting_confirmation","reschedule_requested","cancelled"]
    counselor_note: str | None = Field(default=None,max_length=1000)
    proposed_at: datetime | None = None
class RasaCounterInput(BaseModel):
    requested_at: datetime
class RasaReferralInput(BaseModel):
    summary: str = Field(min_length=10,max_length=1200)
    consent: bool = False
    urgent: bool = False

class RasaBKRequestInput(BaseModel):
    school_id: uuid.UUID
    requested_at: datetime
    mode: Literal["in_person","online"]
    topic: str = Field(min_length=1,max_length=120)
    student_note: str | None = Field(default=None,max_length=1000)

class RasaBKReviewInput(BaseModel):
    proposed_at: datetime
    counselor_note: str | None = Field(default=None,max_length=1000)



def _require_roles(request: Request, *roles: str):
    user = current_user(request)
    if user["role"] not in roles:
        raise HTTPException(403, "Akses tidak diizinkan untuk peran ini.")
    return user


def _audit_event(conn, actor, action: str, entity_type: str, entity_id):
    # Audit metadata only; never write journal, counseling or venting text here.
    conn.execute(
        """INSERT INTO audit_events(school_id, actor_id, action, entity_type, entity_id)
           VALUES (%s, %s, %s, %s, %s)""",
        (actor.get("school_id"), actor["id"], action, entity_type, str(entity_id)),
    )


def _venting_cipher() -> AESGCM:
    raw_key = settings.venting_encryption_key.strip()
    try:
        key = base64.b64decode(raw_key, validate=True)
    except Exception:
        raise HTTPException(503, "VENTING_ENCRYPTION_KEY belum dikonfigurasi dengan benar.")
    if len(key) != 32:
        raise HTTPException(503, "VENTING_ENCRYPTION_KEY harus berupa base64 dari tepat 32 byte.")
    return AESGCM(key)


def _decrypt_venting(row) -> str:
    try:
        nonce = base64.b64decode(row["nonce"], validate=True)
        ciphertext = base64.b64decode(row["encrypted_payload"], validate=True)
        tag = base64.b64decode(row["auth_tag"], validate=True)
        return _venting_cipher().decrypt(nonce, ciphertext + tag, None).decode("utf-8")
    except HTTPException:
        raise
    except Exception:
        # Do not expose ciphertext, plaintext or key details in an error response.
        raise HTTPException(500, "Data curhat tidak dapat dibuka dengan kunci enkripsi saat ini.")


@app.get("/api/school/teachers")
def get_school_teachers(request: Request):
    actor = _require_roles(request, "school_admin")
    if not actor["school_id"]:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, full_name, email FROM users
               WHERE school_id=%s AND role='teacher' AND status='active'
               ORDER BY full_name LIMIT 500""",
            (actor["school_id"],),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/school/teacher-assignments")
def get_school_teacher_assignments(request: Request):
    actor = _require_roles(request, "school_admin")
    if not actor["school_id"]:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        rows = conn.execute(
            """SELECT ta.id, ta.teacher_id, ta.class_id, ta.subject_name, ta.academic_year,
                      u.full_name AS teacher_name, c.name AS class_name
               FROM teacher_assignments ta
               JOIN users u ON u.id=ta.teacher_id
               JOIN school_classes c ON c.id=ta.class_id
               WHERE ta.school_id=%s
               ORDER BY c.name, u.full_name, ta.subject_name LIMIT 1000""",
            (actor["school_id"],),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/school/teacher-assignments", status_code=201)
def create_school_teacher_assignment(payload: TeacherAssignmentInput, request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    subject = payload.subject_name.strip()
    year = payload.academic_year.strip()
    if not subject or len(year) < 4:
        raise HTTPException(422, "Mata pelajaran dan tahun ajaran wajib diisi.")
    with connection() as conn:
        teacher = conn.execute(
            """SELECT id FROM users
               WHERE id=%s AND school_id=%s AND role='teacher' AND status='active'""",
            (payload.teacher_id, school_id),
        ).fetchone()
        if not teacher:
            raise HTTPException(404, "Guru tidak ditemukan di sekolah ini.")
        class_row = conn.execute(
            "SELECT id FROM school_classes WHERE id=%s AND school_id=%s",
            (payload.class_id, school_id),
        ).fetchone()
        if not class_row:
            raise HTTPException(404, "Kelas tidak ditemukan di sekolah ini.")
        item = conn.execute(
            """INSERT INTO teacher_assignments(school_id, teacher_id, class_id, subject_name, academic_year)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (teacher_id, class_id, subject_name, academic_year) DO NOTHING
               RETURNING id, teacher_id, class_id, subject_name, academic_year""",
            (school_id, payload.teacher_id, payload.class_id, subject, year),
        ).fetchone()
        if not item:
            raise HTTPException(409, "Penugasan guru untuk kelas dan mata pelajaran tersebut sudah ada.")
        _audit_event(conn, actor, "teacher_assignment.create", "teacher_assignment", item["id"])
    return {"item": dict(item), "message": "Penugasan guru berhasil disimpan."}


@app.get("/api/school/students")
def get_school_students(request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        rows = conn.execute(
            """SELECT u.id, u.email, u.full_name, u.status,
                      sp.student_number, sp.graduation_year,
                      sp.class_id, c.name AS class_name
               FROM users u
               JOIN student_profiles sp ON sp.user_id=u.id
               LEFT JOIN school_classes c ON c.id=sp.class_id AND c.school_id=u.school_id
               WHERE u.school_id=%s AND u.role='student'
               ORDER BY c.name NULLS LAST, u.full_name
               LIMIT 1000""",
            (school_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/school/users")
def get_school_users(
    request: Request,
    q: str = Query("", max_length=100),
    role: str = Query("all", pattern="^(all|student|teacher|counselor)$"),
    status: str = Query("all", pattern="^(all|active|disabled|pending)$"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")

    filters = ["u.school_id=%s", "u.role IN ('student','teacher','counselor')"]
    params: list[Any] = [school_id]
    if role != "all":
        filters.append("u.role=%s")
        params.append(role)
    if status != "all":
        filters.append("u.status=%s")
        params.append(status)
    search = q.strip()
    if search:
        filters.append("(u.full_name ILIKE %s OR u.email ILIKE %s OR COALESCE(sp.student_number,'') ILIKE %s)")
        params.extend([f"%{search}%"] * 3)
    where_sql = " AND ".join(filters)
    with connection() as conn:
        total = conn.execute(
            f"""SELECT count(*) AS total
                FROM users u
                LEFT JOIN student_profiles sp ON sp.user_id=u.id AND sp.school_id=u.school_id
                WHERE {where_sql}""",
            params,
        ).fetchone()["total"]
        rows = conn.execute(
            f"""SELECT u.id, u.email, u.full_name, u.role, u.status,
                       u.created_at, u.updated_at,
                       sp.student_number, sp.graduation_year, sp.class_id,
                       c.name AS class_name, c.academic_year
                FROM users u
                LEFT JOIN student_profiles sp ON sp.user_id=u.id AND sp.school_id=u.school_id
                LEFT JOIN school_classes c ON c.id=sp.class_id AND c.school_id=u.school_id
                WHERE {where_sql}
                ORDER BY CASE u.role WHEN 'student' THEN 1 WHEN 'teacher' THEN 2 ELSE 3 END,
                         u.full_name
                LIMIT %s OFFSET %s""",
            [*params, limit, offset],
        ).fetchall()
    # Never select password_hash or session/token fields for this endpoint.
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@app.get("/api/school/classes")
def get_school_classes(request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        rows = conn.execute(
            """SELECT c.id, c.name, c.academic_year, c.homeroom_teacher_id,
                      t.full_name AS homeroom_teacher_name,
                      count(sp.user_id)::int AS student_count
               FROM school_classes c
               LEFT JOIN users t ON t.id=c.homeroom_teacher_id
                    AND t.school_id=c.school_id AND t.role='teacher'
               LEFT JOIN student_profiles sp ON sp.class_id=c.id
                    AND sp.school_id=c.school_id
               WHERE c.school_id=%s
               GROUP BY c.id, t.full_name
               ORDER BY c.academic_year DESC, c.name LIMIT 500""",
            (school_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/school/classes", status_code=201)
def create_school_class(payload: SchoolClassInput, request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    name = payload.name.strip()
    year = payload.academic_year.strip()
    if not name or len(year) < 4:
        raise HTTPException(422, "Nama kelas dan tahun ajaran wajib diisi.")
    with connection() as conn:
        duplicate = conn.execute(
            """SELECT id FROM school_classes
               WHERE school_id=%s AND lower(name)=lower(%s) AND academic_year=%s
               LIMIT 1""",
            (school_id, name, year),
        ).fetchone()
        if duplicate:
            raise HTTPException(409, "Kelas dengan nama dan tahun ajaran tersebut sudah ada.")
        item = conn.execute(
            """INSERT INTO school_classes(school_id, name, academic_year)
               VALUES (%s, %s, %s)
               RETURNING id, name, academic_year, homeroom_teacher_id""",
            (school_id, name, year),
        ).fetchone()
        _audit_event(conn, actor, "school_class.create", "school_class", item["id"])
    return {"item": dict(item), "message": "Kelas berhasil dibuat."}


@app.patch("/api/school/classes/{class_id}")
def update_school_class(class_id: uuid.UUID, payload: SchoolClassUpdate, request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    name = payload.name.strip()
    year = payload.academic_year.strip()
    if not name or len(year) < 4:
        raise HTTPException(422, "Nama kelas dan tahun ajaran wajib diisi.")
    with connection() as conn:
        current = conn.execute(
            "SELECT id FROM school_classes WHERE id=%s AND school_id=%s",
            (class_id, school_id),
        ).fetchone()
        if not current:
            raise HTTPException(404, "Kelas tidak ditemukan di sekolah ini.")
        if payload.homeroom_teacher_id:
            teacher = conn.execute(
                """SELECT id FROM users
                   WHERE id=%s AND school_id=%s AND role='teacher' AND status='active'""",
                (payload.homeroom_teacher_id, school_id),
            ).fetchone()
            if not teacher:
                raise HTTPException(400, "Wali kelas harus merupakan akun guru aktif di sekolah ini.")
        try:
            item = conn.execute(
                """UPDATE school_classes
                   SET name=%s, academic_year=%s, homeroom_teacher_id=%s
                   WHERE id=%s AND school_id=%s
                   RETURNING id, name, academic_year, homeroom_teacher_id""",
                (name, year, payload.homeroom_teacher_id, class_id, school_id),
            ).fetchone()
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise HTTPException(409, "Nama kelas dan tahun ajaran tersebut sudah digunakan.") from exc
            raise
        _audit_event(conn, actor, "school_class.update", "school_class", class_id)
    return {"item": dict(item), "message": "Data kelas berhasil diperbarui."}


@app.get("/api/school/account-history")
def get_school_account_history(request: Request, limit: int = Query(100, ge=1, le=200)):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        rows = conn.execute(
            """SELECT ae.id, ae.action, ae.entity_type, ae.entity_id, ae.created_at,
                      actor_user.full_name AS actor_name,
                      target_user.full_name AS target_name,
                      target_user.email AS target_email,
                      target_class.name AS class_name
               FROM audit_events ae
               LEFT JOIN users actor_user ON actor_user.id=ae.actor_id
               LEFT JOIN users target_user
                 ON ae.entity_type='user' AND target_user.id::text=ae.entity_id
                AND target_user.school_id=ae.school_id
               LEFT JOIN school_classes target_class
                 ON ae.entity_type='school_class' AND target_class.id::text=ae.entity_id
                AND target_class.school_id=ae.school_id
               WHERE ae.school_id=%s
                 AND ae.action IN (
                   'school_user.create','school_user.update','school_user.status',
                   'school_user.password_reset','school_class.create','school_class.update'
                 )
               ORDER BY ae.created_at DESC
               LIMIT %s""",
            (school_id, limit),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/school/alumni")
def get_school_alumni(request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, student_user_id, full_name, graduation_year, next_step,
                      institution, program, consent_to_share, created_at
               FROM alumni_profiles WHERE school_id=%s
               ORDER BY graduation_year DESC, full_name LIMIT 1000""",
            (school_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/school/alumni", status_code=201)
def create_school_alumni(payload: SchoolAlumniInput, request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    full_name = payload.full_name.strip()
    if not full_name:
        raise HTTPException(422, "Nama alumni wajib diisi.")
    next_step = (payload.next_step or "").strip() or None
    institution = (payload.institution or "").strip() or None
    program = (payload.program or "").strip() or None
    with connection() as conn:
        item = conn.execute(
            """INSERT INTO alumni_profiles(
                   school_id, student_user_id, full_name, graduation_year,
                   next_step, institution, program, consent_to_share
               )
               VALUES (%s, NULL, %s, %s, %s, %s, %s, %s)
               RETURNING id, full_name, graduation_year, next_step, institution,
                         program, consent_to_share, created_at""",
            (school_id, full_name, payload.graduation_year, next_step,
             institution, program, payload.consent_to_share),
        ).fetchone()
        _audit_event(conn, actor, "school_alumni.create", "alumni_profile", item["id"])
    return {"item": dict(item), "message": "Data alumni berhasil disimpan."}


@app.post("/api/school/users", status_code=201)
def create_school_user(payload: SchoolUserInput, request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")

    full_name = payload.full_name.strip()
    student_number = (payload.student_number or "").strip() or None
    if not full_name:
        raise HTTPException(422, "Nama lengkap wajib diisi.")
    if payload.role == "student" and not student_number:
        raise HTTPException(400, "Nomor induk siswa wajib diisi untuk akun siswa.")
    if payload.role == "student" and not payload.class_id:
        raise HTTPException(400, "Kelas wajib dipilih untuk akun siswa agar rapor dapat dikelola.")

    try:
        with connection() as conn:
            if payload.class_id:
                class_row = conn.execute(
                    "SELECT 1 FROM school_classes WHERE id=%s AND school_id=%s",
                    (payload.class_id, school_id),
                ).fetchone()
                if not class_row:
                    raise HTTPException(400, "Kelas tidak valid untuk sekolah ini.")

            user = conn.execute(
                """INSERT INTO users(school_id, email, full_name, password_hash, role, status)
                   VALUES (%s, %s, %s, %s, %s, 'active')
                   RETURNING id, email, full_name, role, status""",
                (school_id, str(payload.email).strip().lower(), full_name,
                 hash_password(payload.temporary_password), payload.role),
            ).fetchone()

            if payload.role == "student":
                conn.execute(
                    """INSERT INTO student_profiles(user_id, school_id, student_number, class_id, graduation_year)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (user["id"], school_id, student_number, payload.class_id, payload.graduation_year),
                )
            _audit_event(conn, actor, "school_user.create", "user", user["id"])
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            raise HTTPException(409, "Email atau nomor induk siswa sudah digunakan di sekolah ini.") from exc
        raise

    return {"item": dict(user), "message": "Akun berhasil dibuat."}


@app.patch("/api/school/users/{user_id}")
def update_school_user(user_id: uuid.UUID, payload: SchoolUserUpdate, request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    fields = payload.model_fields_set
    if not fields:
        raise HTTPException(422, "Tidak ada perubahan data yang dikirim.")
    with connection() as conn:
        current = conn.execute(
            """SELECT id, email, full_name, role
               FROM users
               WHERE id=%s AND school_id=%s
                 AND role IN ('student','teacher','counselor')
               FOR UPDATE""",
            (user_id, school_id),
        ).fetchone()
        if not current:
            raise HTTPException(404, "Akun tidak ditemukan di sekolah ini.")
        full_name = payload.full_name.strip() if "full_name" in fields and payload.full_name is not None else current["full_name"]
        email = str(payload.email).strip().lower() if "email" in fields and payload.email is not None else current["email"]
        if not full_name or not email:
            raise HTTPException(422, "Nama dan email tidak boleh kosong.")
        if "email" in fields:
            duplicate = conn.execute(
                """SELECT 1 FROM users
                   WHERE school_id=%s AND lower(email)=lower(%s) AND id<>%s
                   LIMIT 1""",
                (school_id, email, user_id),
            ).fetchone()
            if duplicate:
                raise HTTPException(409, "Email sudah digunakan akun lain di sekolah ini.")

        profile = None
        if current["role"] == "student":
            profile = conn.execute(
                """SELECT student_number, class_id, graduation_year
                   FROM student_profiles WHERE user_id=%s AND school_id=%s FOR UPDATE""",
                (user_id, school_id),
            ).fetchone()
            if not profile:
                raise HTTPException(409, "Profil siswa belum tersedia untuk akun ini.")
            student_number = payload.student_number.strip() if "student_number" in fields and payload.student_number is not None else profile["student_number"]
            class_id = payload.class_id if "class_id" in fields else profile["class_id"]
            graduation_year = payload.graduation_year if "graduation_year" in fields else profile["graduation_year"]
            if not student_number:
                raise HTTPException(422, "Nomor induk siswa tidak boleh kosong.")
            if class_id and not conn.execute(
                "SELECT id FROM school_classes WHERE id=%s AND school_id=%s",
                (class_id, school_id),
            ).fetchone():
                raise HTTPException(400, "Kelas yang dipilih tidak valid untuk sekolah ini.")
            try:
                conn.execute(
                    """UPDATE student_profiles
                       SET student_number=%s, class_id=%s, graduation_year=%s
                       WHERE user_id=%s AND school_id=%s""",
                    (student_number, class_id, graduation_year, user_id, school_id),
                )
            except Exception as exc:
                if getattr(exc, "sqlstate", None) == "23505":
                    raise HTTPException(409, "Nomor induk siswa sudah digunakan di sekolah ini.") from exc
                raise
        elif any(field in fields for field in ("student_number", "class_id", "graduation_year")):
            raise HTTPException(400, "Data NIS, kelas, dan tahun lulus hanya berlaku untuk akun siswa.")

        try:
            updated = conn.execute(
                """UPDATE users SET full_name=%s, email=%s, updated_at=now()
                   WHERE id=%s AND school_id=%s
                   RETURNING id, email, full_name, role, status, updated_at""",
                (full_name, email, user_id, school_id),
            ).fetchone()
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise HTTPException(409, "Email sudah digunakan akun lain di sekolah ini.") from exc
            raise
        _audit_event(conn, actor, "school_user.update", "user", user_id)
    result = dict(updated)
    if profile is not None:
        result.update({"student_number": student_number, "class_id": str(class_id) if class_id else None,
                       "graduation_year": graduation_year})
    return {"item": result, "message": "Data akun berhasil diperbarui."}


@app.patch("/api/school/users/{user_id}/status")
def update_school_user_status(user_id: uuid.UUID, payload: SchoolUserStatusInput, request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        item = conn.execute(
            """UPDATE users SET status=%s, updated_at=now()
               WHERE id=%s AND school_id=%s
                 AND role IN ('student','teacher','counselor')
               RETURNING id, email, full_name, role, status, updated_at""",
            (payload.status, user_id, school_id),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Akun tidak ditemukan di sekolah ini.")
        if payload.status == "disabled":
            conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        _audit_event(conn, actor, "school_user.status", "user", user_id)
    return {"item": dict(item), "message": "Status akun berhasil diperbarui."}


@app.post("/api/school/users/{user_id}/reset-password")
def reset_school_user_password(user_id: uuid.UUID, request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        target = conn.execute(
            """SELECT id FROM users
               WHERE id=%s AND school_id=%s
                 AND role IN ('student','teacher','counselor')""",
            (user_id, school_id),
        ).fetchone()
        if not target:
            raise HTTPException(404, "Akun tidak ditemukan di sekolah ini.")
        temporary_password = new_token(24)
        conn.execute(
            """UPDATE users SET password_hash=%s, updated_at=now()
               WHERE id=%s AND school_id=%s""",
            (hash_password(temporary_password), user_id, school_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        _audit_event(conn, actor, "school_user.password_reset", "user", user_id)
    return {
        "temporary_password": temporary_password,
        "message": "Kata sandi sementara dibuat. Catat dan sampaikan kepada pemilik akun melalui kanal terpisah.",
    }


@app.post("/api/platform/users", status_code=201)
def create_platform_moderator(payload: PlatformModeratorInput, request: Request):
    actor = _require_roles(request, "platform_admin")
    full_name = payload.full_name.strip()
    if not full_name:
        raise HTTPException(422, "Nama lengkap wajib diisi.")
    try:
        with connection() as conn:
            user = conn.execute(
                """INSERT INTO users(school_id, email, full_name, password_hash, role, status)
                   VALUES (NULL, %s, %s, %s, 'wellbeing_moderator', 'active')
                   RETURNING id, email, full_name, role, status""",
                (str(payload.email).strip().lower(), full_name, hash_password(payload.temporary_password)),
            ).fetchone()
            _audit_event(conn, actor, "platform_moderator.create", "user", user["id"])
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            raise HTTPException(409, "Email akun platform tersebut sudah digunakan.") from exc
        raise
    return {"item": dict(user), "message": "Akun Moderator Curhat berhasil dibuat."}



@app.post("/api/bk/appointments", status_code=201)
def create_bk_appointment(payload: BKAppointmentInput, request: Request):
    actor = _require_roles(request, "student")
    if not actor["school_id"]: raise HTTPException(403, "Akun siswa belum terhubung ke sekolah.")
    if payload.requested_at.tzinfo is None or payload.requested_at <= datetime.now(payload.requested_at.tzinfo):
        raise HTTPException(422, "Usulan waktu harus berada di masa mendatang dan menyertakan zona waktu.")
    with connection() as conn:
        item=conn.execute("""INSERT INTO bk_appointments(school_id,student_id,requested_at,mode,topic,student_note,status)
          VALUES (%s,%s,%s,%s,%s,%s,'pending_review') RETURNING id,requested_at,mode,topic,status,created_at""",
          (actor["school_id"],actor["id"],payload.requested_at,payload.mode,payload.topic.strip(),payload.student_note.strip() if payload.student_note else None)).fetchone()
        _audit_event(conn,actor,"bk_appointment.create","bk_appointment",item["id"])
    return {"item":dict(item)}

@app.get("/api/bk/appointments/mine")
def get_my_bk_appointments(request: Request):
    actor=_require_roles(request,"student")
    with connection() as conn:
        rows=conn.execute("""SELECT id,requested_at,scheduled_at,mode,topic,student_note,status,counselor_note,created_at,reviewed_at,confirmed_at,student_accepted
          FROM bk_appointments WHERE student_id=%s ORDER BY created_at DESC LIMIT 100""",(actor["id"],)).fetchall()
    return {"items":[dict(r) for r in rows]}

@app.get("/api/bk/appointments")
def get_bk_appointments(request: Request):
    actor=_require_roles(request,"counselor")
    if not actor["school_id"]: raise HTTPException(403,"Akun Guru BK belum terhubung ke sekolah.")
    with connection() as conn:
        rows=conn.execute("""SELECT a.id,a.requested_at,a.scheduled_at,a.mode,a.topic,a.student_note,a.status,a.counselor_note,a.created_at,a.reviewed_at,a.confirmed_at,a.student_accepted,
          u.full_name AS student_name,sp.student_number,sc.name AS class_name
          FROM bk_appointments a JOIN users u ON u.id=a.student_id LEFT JOIN student_profiles sp ON sp.user_id=u.id
          LEFT JOIN school_classes sc ON sc.id=sp.class_id WHERE a.school_id=%s ORDER BY a.created_at ASC LIMIT 500""",(actor["school_id"],)).fetchall()
    return {"items":[dict(r) for r in rows]}

@app.patch("/api/bk/appointments/{appointment_id}/review")
def review_bk_appointment(appointment_id: uuid.UUID,payload:RasaReviewInput,request:Request):
    actor=_require_roles(request,"counselor")
    if payload.proposed_at and (payload.proposed_at.tzinfo is None or payload.proposed_at<=datetime.now(payload.proposed_at.tzinfo)):
        raise HTTPException(422,"Waktu penawaran harus berada di masa mendatang.")
    with connection() as conn:
        row=conn.execute("""UPDATE bk_appointments SET status=%s,counselor_id=%s,scheduled_at=COALESCE(%s,scheduled_at),
          counselor_note=%s,reviewed_at=COALESCE(reviewed_at,now()),student_accepted=false,updated_at=now()
          WHERE id=%s AND school_id=%s RETURNING id,status,requested_at,scheduled_at""",
          (payload.decision,actor["id"],payload.proposed_at,payload.counselor_note,appointment_id,actor["school_id"])).fetchone()
        if not row: raise HTTPException(404,"Permohonan konsultasi tidak ditemukan.")
        _audit_event(conn,actor,"bk_appointment.review","bk_appointment",appointment_id)
    return {"item":dict(row)}

@app.patch("/api/bk/appointments/{appointment_id}/counter-proposal")
def student_counter_propose_bk_schedule(appointment_id:uuid.UUID,payload:RasaCounterInput,request:Request):
    actor=_require_roles(request,"student")
    if payload.requested_at.tzinfo is None or payload.requested_at<=datetime.now(payload.requested_at.tzinfo):
        raise HTTPException(422,"Usulan waktu harus berada di masa mendatang.")
    with connection() as conn:
        row=conn.execute("""UPDATE bk_appointments SET requested_at=%s,status='reschedule_requested',scheduled_at=NULL,student_accepted=false,updated_at=now()
          WHERE id=%s AND student_id=%s AND status='awaiting_confirmation' RETURNING id,status,requested_at""",
          (payload.requested_at,appointment_id,actor["id"])).fetchone()
        if not row: raise HTTPException(409,"Permohonan belum menunggu persetujuan jadwal.")
        _audit_event(conn,actor,"bk_appointment.counter_proposal","bk_appointment",appointment_id)
    return {"item":dict(row)}

@app.patch("/api/bk/appointments/{appointment_id}/confirm-student")
def student_accept_bk_schedule(appointment_id:uuid.UUID,request:Request):
    actor=_require_roles(request,"student")
    with connection() as conn:
        row=conn.execute("""UPDATE bk_appointments SET student_accepted=true,updated_at=now()
          WHERE id=%s AND student_id=%s AND status='awaiting_confirmation' AND scheduled_at IS NOT NULL
          RETURNING id,status,scheduled_at""",(appointment_id,actor["id"])).fetchone()
        if not row: raise HTTPException(409,"Belum ada penawaran jadwal yang dapat disetujui.")
        _audit_event(conn,actor,"bk_appointment.student_accept","bk_appointment",appointment_id)
    return {"item":dict(row)}

@app.patch("/api/bk/appointments/{appointment_id}/confirm")
def counselor_confirm_bk_schedule(appointment_id:uuid.UUID,request:Request):
    actor=_require_roles(request,"counselor")
    with connection() as conn:
        row=conn.execute("""UPDATE bk_appointments SET status='confirmed',confirmed_at=now(),updated_at=now()
          WHERE id=%s AND school_id=%s AND status='awaiting_confirmation' AND student_accepted=true AND scheduled_at IS NOT NULL
          RETURNING id,status,scheduled_at""",(appointment_id,actor["school_id"])).fetchone()
        if not row: raise HTTPException(409,"Jadwal belum disetujui siswa atau permohonan tidak ditemukan.")
        _audit_event(conn,actor,"bk_appointment.confirm","bk_appointment",appointment_id)
    return {"item":dict(row)}

# RASA anonymous encrypted chat. Conversation records never store student identity.
def _rasa_encrypt(value:str):
    nonce=secrets.token_bytes(12); packed=_venting_cipher().encrypt(nonce,value.encode("utf-8"),None)
    return base64.b64encode(packed[:-16]).decode(),base64.b64encode(nonce).decode(),base64.b64encode(packed[-16:]).decode()
def _rasa_decrypt(row):
    nonce=base64.b64decode(row["nonce"],validate=True); data=base64.b64decode(row["encrypted_payload"],validate=True); tag=base64.b64decode(row["auth_tag"],validate=True)
    return _venting_cipher().decrypt(nonce,data+tag,None).decode("utf-8")
def _rasa_access(conn,code):
    row=conn.execute("""SELECT c.id,c.status,c.category,c.created_at FROM rasa_access_codes a JOIN rasa_conversations c ON c.id=a.conversation_id
      WHERE a.code_hash=%s AND a.expires_at>now()""",(digest(code),)).fetchone()
    if not row: raise HTTPException(404,"Kode akses tidak valid atau sudah kedaluwarsa.")
    return row


def _rasa_save_message(conn, conversation_id, sender_type, text, sender_id=None, client_message_id=None):
    encrypted = _rasa_encrypt(text.strip())
    row = conn.execute("""INSERT INTO rasa_messages
      (conversation_id,sender_type,sender_id,encrypted_payload,nonce,auth_tag,client_message_id)
      VALUES (%s,%s,%s,%s,%s,%s,%s)
      ON CONFLICT (conversation_id,sender_type,client_message_id)
        WHERE client_message_id IS NOT NULL DO NOTHING
      RETURNING id,created_at,encrypted_payload,nonce,auth_tag""",
      (conversation_id,sender_type,sender_id,*encrypted,client_message_id)).fetchone()
    inserted = row is not None
    if not row and client_message_id:
        row = conn.execute("""SELECT id,created_at,encrypted_payload,nonce,auth_tag
          FROM rasa_messages WHERE conversation_id=%s AND sender_type=%s AND client_message_id=%s""",
          (conversation_id,sender_type,client_message_id)).fetchone()
    if not row:
        raise HTTPException(409,"Pesan belum dapat disimpan. Silakan kirim ulang.")
    return row, inserted



@app.post("/api/rasa/conversations",status_code=201)
def rasa_create_conversation(payload:RasaConversationInput):
    code=secrets.token_urlsafe(32); encrypted=_rasa_encrypt(payload.text.strip())
    with connection() as conn:
        if payload.school_id:
            school=conn.execute("SELECT id FROM schools WHERE id=%s AND status='active'",(payload.school_id,)).fetchone()
        else:
            active=conn.execute("SELECT id FROM schools WHERE status='active' ORDER BY name LIMIT 2").fetchall()
            school=active[0] if len(active)==1 else None
        if not school: raise HTTPException(422,"Pilih sekolah yang sesuai sebelum memulai percakapan RASA.")
        c=conn.execute("INSERT INTO rasa_conversations(school_id,category,status) VALUES (%s,%s,'unassigned') RETURNING id,status",(school["id"],payload.category)).fetchone()
        conn.execute("INSERT INTO rasa_access_codes(conversation_id,code_hash) VALUES (%s,%s)",(c["id"],digest(code)))
        conn.execute("INSERT INTO rasa_messages(conversation_id,sender_type,encrypted_payload,nonce,auth_tag) VALUES (%s,'visitor',%s,%s,%s)",(c["id"],*encrypted))
    return {"conversation_id":str(c["id"]),"access_code":code,"status":c["status"]}

@app.post("/api/rasa/conversations/access")
def rasa_access_conversation(payload:RasaAccessInput):
    with connection() as conn:
        c=_rasa_access(conn,payload.access_code.strip())
        rows=conn.execute("SELECT id,sender_type,encrypted_payload,nonce,auth_tag,created_at FROM rasa_messages WHERE conversation_id=%s ORDER BY created_at LIMIT 300",(c["id"],)).fetchall()
        typing=conn.execute("SELECT EXISTS(SELECT 1 FROM rasa_typing_presence WHERE conversation_id=%s AND actor_type='moderator' AND is_typing=true AND updated_at>now()-interval '8 seconds') AS typing",(c["id"],)).fetchone()
    return {"conversation":{"id":str(c["id"]),"status":c["status"],"category":c["category"]},"counterpart_typing":bool(typing["typing"]),
      "messages":[{"id":str(m["id"]),"sender":m["sender_type"],"text":_rasa_decrypt(m),"created_at":m["created_at"].isoformat()} for m in rows]}

@app.post("/api/rasa/conversations/{conversation_id}/messages",status_code=201)
def rasa_visitor_message(conversation_id:uuid.UUID,payload:RasaMessageInput,request:Request):
    code=request.headers.get("X-RASA-ACCESS-CODE","").strip()
    with connection() as conn:
        c=_rasa_access(conn,code)
        if str(c["id"])!=str(conversation_id): raise HTTPException(403,"Kode akses tidak cocok.")
        if c["status"] in ("closed","referred"): raise HTTPException(409,"Percakapan telah diselesaikan atau dirujuk dan tidak menerima pesan baru.")
        row,inserted=_rasa_save_message(conn,conversation_id,"visitor",payload.text,client_message_id=payload.client_message_id)
        if inserted:
            conn.execute("UPDATE rasa_conversations SET status='waiting_moderator',updated_at=now(),last_message_at=now() WHERE id=%s",(conversation_id,))
    return {"item":{"id":str(row["id"]),"sender":"visitor","text":_rasa_decrypt(row),"created_at":row["created_at"].isoformat(),"delivery":"sent"}}


class RasaTypingInput(BaseModel):
    is_typing: bool = False

@app.post("/api/rasa/conversations/{conversation_id}/typing")
def rasa_visitor_typing(conversation_id:uuid.UUID,payload:RasaTypingInput,request:Request):
    code=request.headers.get("X-RASA-ACCESS-CODE","").strip()
    with connection() as conn:
        c=_rasa_access(conn,code)
        if str(c["id"])!=str(conversation_id): raise HTTPException(403,"Kode akses tidak cocok.")
        conn.execute("""INSERT INTO rasa_typing_presence(conversation_id,actor_type,actor_key,is_typing,updated_at)
          VALUES (%s,'visitor',%s,%s,now())
          ON CONFLICT(conversation_id,actor_type,actor_key) DO UPDATE
          SET is_typing=EXCLUDED.is_typing,updated_at=now()""",(conversation_id,digest(code),payload.is_typing))
        row=conn.execute("""SELECT EXISTS(SELECT 1 FROM rasa_typing_presence
          WHERE conversation_id=%s AND actor_type='moderator' AND is_typing=true
          AND updated_at>now()-interval '8 seconds') AS typing""",(conversation_id,)).fetchone()
    return {"moderator_typing":bool(row["typing"])}

@app.post("/api/rasa/moderator/conversations/{conversation_id}/typing")
def rasa_moderator_typing(conversation_id:uuid.UUID,payload:RasaTypingInput,request:Request):
    actor=_require_roles(request,"wellbeing_moderator")
    with connection() as conn:
        c=conn.execute("SELECT assigned_moderator_id FROM rasa_conversations WHERE id=%s AND status<>'closed'",(conversation_id,)).fetchone()
        if not c: raise HTTPException(404,"Percakapan tidak ditemukan atau ditutup.")
        if c["assigned_moderator_id"] and str(c["assigned_moderator_id"])!=str(actor["id"]): raise HTTPException(403,"Percakapan ditugaskan ke moderator lain.")
        conn.execute("""INSERT INTO rasa_typing_presence(conversation_id,actor_type,actor_key,is_typing,updated_at)
          VALUES (%s,'moderator',%s,%s,now())
          ON CONFLICT(conversation_id,actor_type,actor_key) DO UPDATE
          SET is_typing=EXCLUDED.is_typing,updated_at=now()""",(conversation_id,str(actor["id"]),payload.is_typing))
        row=conn.execute("""SELECT EXISTS(SELECT 1 FROM rasa_typing_presence
          WHERE conversation_id=%s AND actor_type='visitor' AND is_typing=true
          AND updated_at>now()-interval '8 seconds') AS typing""",(conversation_id,)).fetchone()
    return {"visitor_typing":bool(row["typing"])}


def _rasa_stream_snapshot(conn, conversation_id, counterpart_type):
    c=conn.execute("SELECT id,status,category FROM rasa_conversations WHERE id=%s",(conversation_id,)).fetchone()
    if not c: raise HTTPException(404,"Percakapan tidak ditemukan.")
    rows=conn.execute("SELECT id,sender_type,encrypted_payload,nonce,auth_tag,created_at FROM rasa_messages WHERE conversation_id=%s ORDER BY created_at LIMIT 300",(conversation_id,)).fetchall()
    typing=conn.execute("SELECT EXISTS(SELECT 1 FROM rasa_typing_presence WHERE conversation_id=%s AND actor_type=%s AND is_typing=true AND updated_at>now()-interval '8 seconds') AS typing",(conversation_id,counterpart_type)).fetchone()
    return {"conversation":{"id":str(c["id"]),"status":c["status"],"category":c["category"]},
      "counterpart_typing":bool(typing["typing"]),
      "messages":[{"id":str(m["id"]),"sender":m["sender_type"],"text":_rasa_decrypt(m),"created_at":m["created_at"].isoformat()} for m in rows]}


@app.get("/api/rasa/conversations/{conversation_id}/stream")
def rasa_visitor_stream(conversation_id:uuid.UUID,request:Request):
    code=request.headers.get("X-RASA-ACCESS-CODE","").strip()
    with connection() as conn:
        c=_rasa_access(conn,code)
        if str(c["id"])!=str(conversation_id): raise HTTPException(403,"Kode akses tidak cocok.")
    def events():
        deadline=monotonic()+45
        signature=None
        while monotonic()<deadline:
            with connection() as conn:
                snapshot=_rasa_stream_snapshot(conn,conversation_id,"moderator")
            current=(len(snapshot["messages"]),snapshot["messages"][-1]["id"] if snapshot["messages"] else "",snapshot["conversation"]["status"],snapshot["counterpart_typing"])
            if current!=signature:
                signature=current
                yield "event: update\ndata: "+json.dumps(snapshot,separators=(",",":"))+"\n\n"
            else:
                yield ": keep-alive\n\n"
            sleep(0.8)
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no"})


@app.get("/api/rasa/moderator/conversations/{conversation_id}/stream")
def rasa_moderator_stream(conversation_id:uuid.UUID,request:Request):
    actor=_require_roles(request,"wellbeing_moderator")
    with connection() as conn:
        c=conn.execute("SELECT assigned_moderator_id FROM rasa_conversations WHERE id=%s",(conversation_id,)).fetchone()
        if not c: raise HTTPException(404,"Percakapan tidak ditemukan.")
        if c["assigned_moderator_id"] and str(c["assigned_moderator_id"])!=str(actor["id"]): raise HTTPException(403,"Percakapan ditugaskan ke moderator lain.")
    def events():
        deadline=monotonic()+45
        signature=None
        while monotonic()<deadline:
            with connection() as conn:
                snapshot=_rasa_stream_snapshot(conn,conversation_id,"visitor")
            current=(len(snapshot["messages"]),snapshot["messages"][-1]["id"] if snapshot["messages"] else "",snapshot["conversation"]["status"],snapshot["counterpart_typing"])
            if current!=signature:
                signature=current
                yield "event: update\ndata: "+json.dumps(snapshot,separators=(",",":"))+"\n\n"
            else:
                yield ": keep-alive\n\n"
            sleep(0.8)
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no"})



@app.get("/api/rasa/moderator/queue/stream")
def rasa_moderator_queue_stream(request:Request):
    actor=_require_roles(request,"wellbeing_moderator")
    def events():
        deadline=monotonic()+45
        signature=None
        while monotonic()<deadline:
            with connection() as conn:
                rows=conn.execute("""SELECT c.id,c.category,c.status,c.created_at,c.last_message_at,c.assigned_moderator_id,
                  (SELECT count(*) FROM rasa_messages m WHERE m.conversation_id=c.id) message_count
                  FROM rasa_conversations c WHERE c.status NOT IN ('closed','referred')
                  ORDER BY (c.assigned_moderator_id IS NULL) DESC,c.last_message_at DESC LIMIT 200""").fetchall()
            items=[{**dict(r),"id":str(r["id"]),"assigned_to_me":bool(r["assigned_moderator_id"] and str(r["assigned_moderator_id"])==str(actor["id"]))} for r in rows]
            serialized=json.dumps(items,default=str,separators=(",",":"))
            if serialized!=signature:
                signature=serialized
                yield "event: update\ndata: "+json.dumps({"items":items},default=str,separators=(",",":"))+"\n\n"
            else:
                yield ": keep-alive\n\n"
            sleep(0.8)
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no"})


@app.get("/api/rasa/moderator/queue")
def rasa_moderator_queue(request:Request):
    actor=_require_roles(request,"wellbeing_moderator")
    with connection() as conn:
        rows=conn.execute("""SELECT c.id,c.category,c.status,c.created_at,c.last_message_at,c.assigned_moderator_id,
          (SELECT count(*) FROM rasa_messages m WHERE m.conversation_id=c.id) message_count
          FROM rasa_conversations c WHERE c.status NOT IN ('closed','referred') ORDER BY (c.assigned_moderator_id IS NULL) DESC,c.last_message_at DESC LIMIT 200""").fetchall()
    return {"items":[{**dict(r),"id":str(r["id"]),"assigned_to_me":bool(r["assigned_moderator_id"] and str(r["assigned_moderator_id"])==str(actor["id"]))} for r in rows]}

@app.get("/api/rasa/moderator/history")
def rasa_moderator_history(request:Request):
    actor=_require_roles(request,"wellbeing_moderator")
    with connection() as conn:
        rows=conn.execute("""SELECT c.id,c.category,c.status,c.updated_at,c.last_message_at,
          (SELECT count(*) FROM rasa_messages m WHERE m.conversation_id=c.id) message_count
          FROM rasa_conversations c
          WHERE c.assigned_moderator_id=%s AND c.status IN ('closed','referred')
          ORDER BY c.updated_at DESC LIMIT 300""",(actor["id"],)).fetchall()
    return {"items":[{**dict(r),"id":str(r["id"])} for r in rows]}


@app.post("/api/rasa/moderator/conversations/{conversation_id}/assign")
def rasa_assign(conversation_id:uuid.UUID,request:Request):
    actor=_require_roles(request,"wellbeing_moderator")
    with connection() as conn:
        row=conn.execute("""UPDATE rasa_conversations SET assigned_moderator_id=%s,status='assigned',updated_at=now()
          WHERE id=%s AND status<>'closed' AND (assigned_moderator_id IS NULL OR assigned_moderator_id=%s) RETURNING id""",
          (actor["id"],conversation_id,actor["id"])).fetchone()
        if not row: raise HTTPException(409,"Percakapan sudah ditangani moderator lain atau telah ditutup.")
        _audit_event(conn,actor,"rasa.assign","rasa_conversation",conversation_id)
    return {"ok":True}

@app.get("/api/rasa/moderator/conversations/{conversation_id}")
def rasa_moderator_messages(conversation_id:uuid.UUID,request:Request):
    actor=_require_roles(request,"wellbeing_moderator")
    with connection() as conn:
        c=conn.execute("SELECT id,status,category,assigned_moderator_id FROM rasa_conversations WHERE id=%s",(conversation_id,)).fetchone()
        if not c: raise HTTPException(404,"Percakapan tidak ditemukan.")
        if c["assigned_moderator_id"] and str(c["assigned_moderator_id"])!=str(actor["id"]): raise HTTPException(403,"Percakapan ditugaskan ke moderator lain.")
        rows=conn.execute("SELECT id,sender_type,encrypted_payload,nonce,auth_tag,created_at FROM rasa_messages WHERE conversation_id=%s ORDER BY created_at LIMIT 300",(conversation_id,)).fetchall()
        typing=conn.execute("SELECT EXISTS(SELECT 1 FROM rasa_typing_presence WHERE conversation_id=%s AND actor_type='visitor' AND is_typing=true AND updated_at>now()-interval '8 seconds') AS typing",(conversation_id,)).fetchone()
    return {"conversation":{"id":str(c["id"]),"status":c["status"],"category":c["category"]},"counterpart_typing":bool(typing["typing"]),
      "messages":[{"id":str(m["id"]),"sender":m["sender_type"],"text":_rasa_decrypt(m),"created_at":m["created_at"].isoformat()} for m in rows]}

@app.post("/api/rasa/moderator/conversations/{conversation_id}/messages",status_code=201)
def rasa_moderator_message(conversation_id:uuid.UUID,payload:RasaMessageInput,request:Request):
    actor=_require_roles(request,"wellbeing_moderator")
    with connection() as conn:
        c=conn.execute("SELECT assigned_moderator_id FROM rasa_conversations WHERE id=%s AND status<>'closed'",(conversation_id,)).fetchone()
        if not c: raise HTTPException(404,"Percakapan tidak ditemukan atau ditutup.")
        if c["assigned_moderator_id"] and str(c["assigned_moderator_id"])!=str(actor["id"]): raise HTTPException(403,"Percakapan ditugaskan ke moderator lain.")
        row,inserted=_rasa_save_message(conn,conversation_id,"moderator",payload.text,sender_id=actor["id"],client_message_id=payload.client_message_id)
        if inserted:
            conn.execute("UPDATE rasa_conversations SET status='waiting_student',updated_at=now(),last_message_at=now() WHERE id=%s",(conversation_id,))
    return {"item":{"id":str(row["id"]),"sender":"moderator","text":_rasa_decrypt(row),"created_at":row["created_at"].isoformat(),"delivery":"sent"}}

@app.patch("/api/rasa/moderator/conversations/{conversation_id}/status")
def rasa_status(conversation_id:uuid.UUID,payload:dict,request:Request):
    actor=_require_roles(request,"wellbeing_moderator"); status=payload.get("status")
    if status not in ("waiting_student","waiting_moderator","closed"): raise HTTPException(422,"Status tidak valid.")
    with connection() as conn:
        row=conn.execute("UPDATE rasa_conversations SET status=%s,updated_at=now() WHERE id=%s AND assigned_moderator_id=%s RETURNING id,status",(status,conversation_id,actor["id"])).fetchone()
        if not row: raise HTTPException(404,"Percakapan tidak ditemukan atau bukan penugasanmu.")
        _audit_event(conn,actor,"rasa.status","rasa_conversation",conversation_id)
    return {"item":dict(row)}

@app.post("/api/rasa/moderator/conversations/{conversation_id}/referral")
def rasa_referral(conversation_id:uuid.UUID,payload:RasaReferralInput,request:Request):
    actor=_require_roles(request,"wellbeing_moderator")
    if not payload.consent and not payload.urgent: raise HTTPException(422,"Persetujuan siswa diperlukan kecuali ada risiko keselamatan mendesak sesuai kebijakan sekolah.")
    with connection() as conn:
        c=conn.execute("SELECT id,school_id FROM rasa_conversations WHERE id=%s AND assigned_moderator_id=%s",(conversation_id,actor["id"])).fetchone()
        if not c: raise HTTPException(404,"Percakapan bukan penugasanmu.")
        if not c["school_id"]: raise HTTPException(422,"Percakapan belum terhubung ke sekolah, sehingga tidak dapat dirujuk ke Guru BK.")
        counselor=conn.execute("SELECT id FROM users WHERE role='counselor' AND status='active' AND school_id=%s LIMIT 1",(c["school_id"],)).fetchone()
        if not counselor: raise HTTPException(409,"Belum ada akun Guru BK aktif yang terhubung ke sekolah percakapan ini.")
        conn.execute("""INSERT INTO rasa_referrals(conversation_id,moderator_id,school_id,summary,consent,urgent)
          VALUES(%s,%s,%s,%s,%s,%s)""",
          (conversation_id,actor["id"],c["school_id"],payload.summary.strip(),payload.consent,payload.urgent))
        conn.execute("UPDATE rasa_conversations SET status='referred',updated_at=now() WHERE id=%s",(conversation_id,))
        _audit_event(conn,actor,"rasa.referral","rasa_conversation",conversation_id)
    return {"ok":True}

@app.patch("/api/rasa/bk/referrals/{referral_id}/status")
def rasa_bk_referral_status(referral_id:uuid.UUID,payload:dict,request:Request):
    actor=_require_roles(request,"counselor")
    status=payload.get("status")
    if status not in ("accepted","closed"): raise HTTPException(422,"Status rujukan tidak valid.")
    if not actor.get("school_id"): raise HTTPException(403,"Akun Guru BK belum terhubung ke sekolah.")
    with connection() as conn:
        row=conn.execute("""UPDATE rasa_referrals SET status=%s
          WHERE id=%s AND school_id=%s AND status IN ('pending','accepted')
          RETURNING id,status""",(status,referral_id,actor["school_id"])).fetchone()
        if not row: raise HTTPException(404,"Rujukan tidak ditemukan atau bukan untuk sekolahmu.")
        _audit_event(conn,actor,"rasa.referral.status","rasa_referral",referral_id)
    return {"item":dict(row)}


@app.get("/api/rasa/bk/referrals")
def rasa_bk_referrals(request:Request):
    actor=_require_roles(request,"counselor")
    if not actor.get("school_id"): raise HTTPException(403,"Akun Guru BK belum terhubung ke sekolah.")
    with connection() as conn:
        rows=conn.execute("""SELECT r.id,r.summary,r.consent,r.urgent,r.status,r.created_at
          FROM rasa_referrals r
          WHERE r.status IN ('pending','accepted') AND r.school_id=%s
          ORDER BY r.urgent DESC,r.created_at LIMIT 100""",(actor["school_id"],)).fetchall()
    return {"items":[dict(r) for r in rows]}

@app.get("/api/public/schools")
def public_active_schools():
    with connection() as conn:
        rows=conn.execute("SELECT id,name FROM schools WHERE status='active' ORDER BY name").fetchall()
    return {"items":[{"id":str(r["id"]),"name":r["name"]} for r in rows]}

@app.post("/api/rasa/bk/requests",status_code=201)
def rasa_create_anonymous_bk_request(payload:RasaBKRequestInput):
    if payload.requested_at.tzinfo is None or payload.requested_at <= datetime.now(payload.requested_at.tzinfo):
        raise HTTPException(422,"Waktu usulan harus berada di masa mendatang dan menyertakan zona waktu.")
    code=secrets.token_urlsafe(32)
    encrypted=_rasa_encrypt(json.dumps({"topic":payload.topic.strip(),"student_note":(payload.student_note or "").strip()},ensure_ascii=False))
    with connection() as conn:
        school=conn.execute("SELECT id FROM schools WHERE id=%s AND status='active'",(payload.school_id,)).fetchone()
        if not school: raise HTTPException(404,"Sekolah tidak ditemukan atau tidak aktif.")
        row=conn.execute("""INSERT INTO rasa_bk_requests(school_id,code_hash,requested_at,mode,encrypted_payload,nonce,auth_tag)
          VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id,status,requested_at,mode,expires_at""",
          (payload.school_id,digest(code),payload.requested_at,payload.mode,*encrypted)).fetchone()
    return {"item":{**dict(row),"id":str(row["id"])},"access_code":code}

@app.post("/api/rasa/bk/requests/access")
def rasa_access_anonymous_bk_request(payload:RasaAccessInput):
    with connection() as conn:
        row=conn.execute("""SELECT id,status,requested_at,mode,scheduled_at,counselor_note,expires_at
          FROM rasa_bk_requests WHERE code_hash=%s AND expires_at>now()""",(digest(payload.access_code.strip()),)).fetchone()
    if not row: raise HTTPException(404,"Kode konsultasi tidak valid atau sudah kedaluwarsa.")
    return {"item":{**dict(row),"id":str(row["id"])}}

@app.patch("/api/rasa/bk/requests/{request_id}/counter-proposal")
def rasa_anonymous_bk_counter(request_id:uuid.UUID,payload:RasaCounterInput,request:Request):
    code=request.headers.get("X-RASA-ACCESS-CODE","").strip()
    if payload.requested_at.tzinfo is None or payload.requested_at<=datetime.now(payload.requested_at.tzinfo):
        raise HTTPException(422,"Waktu usulan harus berada di masa mendatang.")
    with connection() as conn:
        row=conn.execute("""UPDATE rasa_bk_requests SET requested_at=%s,status='reschedule_requested',scheduled_at=NULL,
          student_accepted=false,updated_at=now() WHERE id=%s AND code_hash=%s AND expires_at>now()
          AND status='awaiting_confirmation' RETURNING id,status,requested_at""",
          (payload.requested_at,request_id,digest(code))).fetchone()
    if not row: raise HTTPException(409,"Kode tidak cocok atau permohonan belum menunggu persetujuan jadwal.")
    return {"item":{**dict(row),"id":str(row["id"])}}

@app.patch("/api/rasa/bk/requests/{request_id}/confirm-student")
def rasa_anonymous_bk_student_accept(request_id:uuid.UUID,request:Request):
    code=request.headers.get("X-RASA-ACCESS-CODE","").strip()
    with connection() as conn:
        row=conn.execute("""UPDATE rasa_bk_requests SET student_accepted=true,updated_at=now()
          WHERE id=%s AND code_hash=%s AND expires_at>now() AND status='awaiting_confirmation' AND scheduled_at IS NOT NULL
          RETURNING id,status,scheduled_at""",(request_id,digest(code))).fetchone()
    if not row: raise HTTPException(409,"Kode tidak cocok atau belum ada jadwal yang dapat disetujui.")
    return {"item":{**dict(row),"id":str(row["id"])}}

@app.get("/api/rasa/bk/requests")
def rasa_bk_anonymous_queue(request:Request):
    actor=_require_roles(request,"counselor")
    if not actor["school_id"]: raise HTTPException(403,"Akun Guru BK belum terhubung ke sekolah.")
    with connection() as conn:
        rows=conn.execute("""SELECT id,requested_at,mode,status,scheduled_at,counselor_note,student_accepted,created_at,
          encrypted_payload,nonce,auth_tag FROM rasa_bk_requests WHERE school_id=%s
          AND status NOT IN ('completed','cancelled') ORDER BY created_at LIMIT 300""",(actor["school_id"],)).fetchall()
    items=[]
    for row in rows:
        try: details=json.loads(_rasa_decrypt(row))
        except Exception: details={"topic":"Permohonan anonim","student_note":""}
        items.append({"id":str(row["id"]),"requested_at":row["requested_at"].isoformat(),"mode":row["mode"],
          "status":row["status"],"scheduled_at":row["scheduled_at"].isoformat() if row["scheduled_at"] else None,
          "counselor_note":row["counselor_note"],"student_accepted":bool(row["student_accepted"]),
          "created_at":row["created_at"].isoformat(),"topic":details.get("topic","Permohonan anonim"),
          "student_note":details.get("student_note","")})
    return {"items":items}

@app.patch("/api/rasa/bk/requests/{request_id}/review")
def rasa_bk_anonymous_review(request_id:uuid.UUID,payload:RasaBKReviewInput,request:Request):
    actor=_require_roles(request,"counselor")
    if payload.proposed_at.tzinfo is None or payload.proposed_at<=datetime.now(payload.proposed_at.tzinfo):
        raise HTTPException(422,"Waktu penawaran harus berada di masa mendatang.")
    with connection() as conn:
        row=conn.execute("""UPDATE rasa_bk_requests SET status='awaiting_confirmation',counselor_id=%s,
          scheduled_at=%s,counselor_note=%s,reviewed_at=COALESCE(reviewed_at,now()),student_accepted=false,updated_at=now()
          WHERE id=%s AND school_id=%s AND status IN ('pending_review','reschedule_requested')
          RETURNING id,status,scheduled_at""",(actor["id"],payload.proposed_at,(payload.counselor_note or "").strip(),request_id,actor["school_id"])).fetchone()
        if not row: raise HTTPException(404,"Permohonan anonim tidak ditemukan atau sudah diproses.")
        _audit_event(conn,actor,"rasa_bk_request.review","rasa_bk_request",request_id)
    return {"item":{**dict(row),"id":str(row["id"])}}

@app.patch("/api/rasa/bk/requests/{request_id}/confirm")
def rasa_bk_anonymous_confirm(request_id:uuid.UUID,request:Request):
    actor=_require_roles(request,"counselor")
    with connection() as conn:
        row=conn.execute("""UPDATE rasa_bk_requests SET status='confirmed',confirmed_at=now(),updated_at=now()
          WHERE id=%s AND school_id=%s AND status='awaiting_confirmation' AND student_accepted=true
          AND scheduled_at IS NOT NULL RETURNING id,status,scheduled_at""",(request_id,actor["school_id"])).fetchone()
        if not row: raise HTTPException(409,"Jadwal belum disetujui pemohon atau permohonan tidak ditemukan.")
        _audit_event(conn,actor,"rasa_bk_request.confirm","rasa_bk_request",request_id)
    return {"item":{**dict(row),"id":str(row["id"])}}

@app.post("/api/anonymous-ventings", status_code=201)
def create_anonymous_venting(payload: AnonymousVentingInput, request: Request):
    # Require a signed-in student, but deliberately do not persist the student identity.
    _require_roles(request, "student")
    text_value = payload.text.strip()
    if len(text_value) < 3:
        raise HTTPException(422, "Isi curhat minimal 3 karakter.")
    cipher = _venting_cipher()
    nonce = secrets.token_bytes(12)
    encrypted_and_tag = cipher.encrypt(nonce, text_value.encode("utf-8"), None)
    ciphertext, tag = encrypted_and_tag[:-16], encrypted_and_tag[-16:]
    with connection() as conn:
        row = conn.execute(
            """INSERT INTO anonymous_ventings(encrypted_payload, nonce, auth_tag, broad_category)
               VALUES (%s, %s, %s, %s)
               RETURNING id, received_day, status""",
            (base64.b64encode(ciphertext).decode("ascii"),
             base64.b64encode(nonce).decode("ascii"),
             base64.b64encode(tag).decode("ascii"), payload.category),
        ).fetchone()
    return {"item": {
        "id": str(row["id"]), "received_day": row["received_day"], "status": "received",
        "message": "Curhat diterima tanpa mengaitkannya dengan akun."
    }}


@app.get("/api/anonymous-ventings")
def get_anonymous_ventings(request: Request):
    _require_roles(request, "wellbeing_moderator")
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, encrypted_payload, nonce, auth_tag, broad_category, received_day, status
               FROM anonymous_ventings WHERE status <> 'closed'
               ORDER BY received_day DESC LIMIT 200"""
        ).fetchall()
    return {"items": [{
        "id": str(row["id"]), "text": _decrypt_venting(row),
        "category": row["broad_category"], "received_day": row["received_day"], "status": row["status"]
    } for row in rows]}


@app.patch("/api/anonymous-ventings/{venting_id}/status")
def update_anonymous_venting_status(venting_id: uuid.UUID, payload: AnonymousVentingStatusInput, request: Request):
    actor = _require_roles(request, "wellbeing_moderator")
    with connection() as conn:
        row = conn.execute(
            """UPDATE anonymous_ventings SET status=%s WHERE id=%s
               RETURNING id, status, received_day""",
            (payload.status, venting_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Curhat tidak ditemukan.")
        _audit_event(conn, actor, "anonymous_venting.status", "anonymous_venting", venting_id)
    return {"item": dict(row)}


# Legacy API paths that are intentionally explicit rather than silently pretending to work.
@app.get("/api/{path:path}")
def unimplemented_get(path: str):
    if path.startswith(("bk/","school/","anonymous-ventings")):
        raise HTTPException(501, "Endpoint ini belum dimigrasikan ke Python. Lihat docs/MIGRATION_STATUS.md.")
    raise HTTPException(404, "Endpoint tidak ditemukan.")


@app.api_route("/api/{path:path}", methods=["POST", "PATCH", "PUT", "DELETE"])
def unimplemented_write(path: str):
    raise HTTPException(501, "Endpoint ini belum dimigrasikan ke Python. Lihat docs/MIGRATION_STATUS.md.")

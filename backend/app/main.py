"""JALUR Python API — FastAPI migration from the original Node backend."""
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from time import monotonic
import secrets, uuid
import base64
from datetime import datetime
from typing import Literal, Any
import json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
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
    opts = {"max_age": settings.session_ttl_hours*3600, "secure": settings.cookie_secure,
            "samesite": "none" if settings.cookie_secure else "lax"}
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


@app.get("/api/school/classes")
def get_school_classes(request: Request):
    actor = _require_roles(request, "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, name, academic_year, homeroom_teacher_id
               FROM school_classes WHERE school_id=%s
               ORDER BY academic_year DESC, name LIMIT 500""",
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
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun siswa belum terhubung ke sekolah.")
    if payload.requested_at.tzinfo is None or payload.requested_at.utcoffset() is None:
        raise HTTPException(422, "Tanggal konsultasi harus menyertakan zona waktu.")
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(422, "Topik konsultasi wajib diisi.")

    with connection() as conn:
        item = conn.execute(
            """INSERT INTO bk_appointments(school_id, student_id, requested_at, mode, topic, student_note)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, requested_at, mode, topic, status, created_at""",
            (school_id, actor["id"], payload.requested_at, payload.mode, topic,
             (payload.student_note or "").strip() or None),
        ).fetchone()
        _audit_event(conn, actor, "bk_appointment.create", "bk_appointment", item["id"])
    return {"item": dict(item)}


@app.get("/api/bk/appointments")
def get_bk_appointments(request: Request):
    actor = _require_roles(request, "counselor", "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun Guru BK/pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.requested_at, a.mode, a.topic, a.student_note, a.status, a.created_at,
                      u.full_name AS student_name, sp.student_number, sc.name AS class_name
               FROM bk_appointments a
               JOIN users u ON u.id=a.student_id
               LEFT JOIN student_profiles sp ON sp.user_id=u.id
               LEFT JOIN school_classes sc ON sc.id=sp.class_id
               WHERE a.school_id=%s
               ORDER BY a.requested_at ASC LIMIT 500""",
            (school_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.patch("/api/bk/appointments/{appointment_id}/status")
def update_bk_appointment_status(appointment_id: uuid.UUID, payload: BKAppointmentStatusInput, request: Request):
    actor = _require_roles(request, "counselor", "school_admin")
    school_id = actor["school_id"]
    if not school_id:
        raise HTTPException(403, "Akun Guru BK/pengelola belum terhubung ke sekolah.")
    with connection() as conn:
        item = conn.execute(
            """UPDATE bk_appointments SET status=%s, counselor_id=%s, updated_at=now()
               WHERE id=%s AND school_id=%s
               RETURNING id, status, requested_at""",
            (payload.status, actor["id"], appointment_id, school_id),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Permintaan konsultasi tidak ditemukan.")
        _audit_event(conn, actor, "bk_appointment.status", "bk_appointment", appointment_id)
    return {"item": dict(item)}


@app.post("/api/anonymous-ventings", status_code=201)
def create_anonymous_venting(payload: AnonymousVentingInput):
    # Intentionally public and unlinked: no user/session/IP identifier is stored.
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

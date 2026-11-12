CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS schools (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, code text UNIQUE NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), school_id uuid REFERENCES schools(id),
  email text NOT NULL, full_name text NOT NULL, password_hash text NOT NULL,
  role text NOT NULL CHECK (role IN ('student','school_admin','teacher','counselor','wellbeing_moderator','platform_admin')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled','pending')),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (school_id, email)
);
CREATE UNIQUE INDEX IF NOT EXISTS users_platform_email_unique ON users (lower(email)) WHERE school_id IS NULL;
CREATE TABLE IF NOT EXISTS sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash text UNIQUE NOT NULL, csrf_hash text NOT NULL, expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS school_classes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), school_id uuid NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
  name text NOT NULL, academic_year text NOT NULL, homeroom_teacher_id uuid REFERENCES users(id),
  UNIQUE(school_id, name, academic_year)
);
CREATE TABLE IF NOT EXISTS student_profiles (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
  student_number text NOT NULL, class_id uuid REFERENCES school_classes(id), graduation_year integer,
  UNIQUE(school_id, student_number)
);
CREATE TABLE IF NOT EXISTS teacher_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), school_id uuid NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
  teacher_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, class_id uuid NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
  subject_name text NOT NULL, academic_year text NOT NULL,
  UNIQUE(teacher_id, class_id, subject_name, academic_year)
);
CREATE TABLE IF NOT EXISTS grades (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), school_id uuid NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
  student_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, teacher_id uuid NOT NULL REFERENCES users(id),
  class_id uuid NOT NULL REFERENCES school_classes(id), subject_name text NOT NULL,
  semester text NOT NULL, academic_year text NOT NULL, score numeric(5,2) NOT NULL CHECK(score >= 0 AND score <= 100),
  notes text, version integer NOT NULL DEFAULT 1, updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(student_id, subject_name, semester, academic_year)
);
CREATE INDEX IF NOT EXISTS grades_student_idx ON grades(student_id, academic_year, semester);
CREATE TABLE IF NOT EXISTS alumni_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), school_id uuid NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
  student_user_id uuid REFERENCES users(id) ON DELETE SET NULL, full_name text NOT NULL,
  graduation_year integer NOT NULL, next_step text, institution text, program text,
  consent_to_share boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS bk_appointments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), school_id uuid NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
  student_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, counselor_id uuid REFERENCES users(id),
  requested_at timestamptz NOT NULL, mode text NOT NULL CHECK(mode IN ('in_person','online')),
  topic text NOT NULL, student_note text, status text NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','confirmed','reschedule_requested','completed','cancelled')),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bk_appointments_school_time_idx ON bk_appointments(school_id, requested_at);
-- Curhat anonim tidak menyimpan user_id, email, school_id, alamat IP, user-agent, atau session ID.
-- Payload dienkripsi oleh aplikasi; tabel menyimpan hanya ciphertext, nonce, tag, kategori umum, dan tanggal.
CREATE TABLE IF NOT EXISTS anonymous_ventings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), encrypted_payload text NOT NULL,
  nonce text NOT NULL, auth_tag text NOT NULL,
  broad_category text NOT NULL CHECK(broad_category IN ('academic','family','friends','future','wellbeing','other')),
  received_day date NOT NULL DEFAULT CURRENT_DATE,
  status text NOT NULL DEFAULT 'unreviewed' CHECK(status IN ('unreviewed','reviewed','resource_shared','closed')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS anonymous_ventings_status_idx ON anonymous_ventings(status, received_day);
CREATE TABLE IF NOT EXISTS audit_events (
  id bigserial PRIMARY KEY, school_id uuid REFERENCES schools(id), actor_id uuid REFERENCES users(id) ON DELETE SET NULL,
  action text NOT NULL, entity_type text NOT NULL, entity_id text, created_at timestamptz NOT NULL DEFAULT now()
);
-- Audit log sengaja tidak menyimpan isi rapor, isi curhat, catatan konseling, kata sandi, atau token.
-- Direktori nasional yang berasal dari data terintegrasi JALUR; simpan baris sumber lengkap sebagai JSONB.
CREATE TABLE IF NOT EXISTS directory_institutions (
  id text PRIMARY KEY, name text NOT NULL, search_text text NOT NULL, data jsonb NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS directory_programs (
  id text PRIMARY KEY, institution_id text, name text NOT NULL, institution_name text NOT NULL,
  level text, field text, search_text text NOT NULL, data jsonb NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS directory_institutions_name_idx ON directory_institutions(lower(name));
CREATE INDEX IF NOT EXISTS directory_institutions_search_idx ON directory_institutions USING gin(to_tsvector('simple', search_text));
CREATE INDEX IF NOT EXISTS directory_programs_name_idx ON directory_programs(lower(name));
CREATE INDEX IF NOT EXISTS directory_programs_institution_idx ON directory_programs(lower(institution_name));
CREATE INDEX IF NOT EXISTS directory_programs_search_idx ON directory_programs USING gin(to_tsvector('simple', search_text));

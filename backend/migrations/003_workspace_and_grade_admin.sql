-- Add a per-student cloud workspace and allow school-admin grade entries.
CREATE TABLE IF NOT EXISTS student_workspaces (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
  workspace_data jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(workspace_data) = 'object'),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS student_workspaces_school_updated_idx
  ON student_workspaces (school_id, updated_at DESC);
ALTER TABLE student_workspaces ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE student_workspaces FROM PUBLIC, anon, authenticated;
ALTER TABLE grades ALTER COLUMN teacher_id DROP NOT NULL;
CREATE INDEX IF NOT EXISTS grades_school_class_subject_idx
  ON grades (school_id, class_id, academic_year, semester, subject_name);

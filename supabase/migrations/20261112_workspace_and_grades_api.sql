-- Persist student workspace server-side and allow school administrators to record grades without impersonating a teacher.
CREATE TABLE IF NOT EXISTS public.student_workspaces (
  user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  school_id uuid NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
  workspace_data jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(workspace_data) = 'object'),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS student_workspaces_school_updated_idx
  ON public.student_workspaces (school_id, updated_at DESC);
ALTER TABLE public.student_workspaces ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.student_workspaces FROM PUBLIC, anon, authenticated;

-- teacher_id remains attributable when a teacher enters a grade; school-admin entries can leave it NULL.
ALTER TABLE public.grades ALTER COLUMN teacher_id DROP NOT NULL;
CREATE INDEX IF NOT EXISTS grades_school_class_subject_idx
  ON public.grades (school_id, class_id, academic_year, semester, subject_name);

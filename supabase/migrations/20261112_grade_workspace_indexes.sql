CREATE INDEX IF NOT EXISTS grades_teacher_id_idx ON public.grades(teacher_id);
CREATE INDEX IF NOT EXISTS grades_class_id_idx ON public.grades(class_id);
CREATE INDEX IF NOT EXISTS student_profiles_class_id_idx ON public.student_profiles(class_id);
CREATE INDEX IF NOT EXISTS teacher_assignments_teacher_id_idx ON public.teacher_assignments(teacher_id);
CREATE INDEX IF NOT EXISTS bk_appointments_student_id_idx ON public.bk_appointments(student_id);
CREATE INDEX IF NOT EXISTS bk_appointments_counselor_id_idx ON public.bk_appointments(counselor_id);
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON public.sessions(user_id);

CREATE INDEX IF NOT EXISTS grades_teacher_id_idx ON grades(teacher_id);
CREATE INDEX IF NOT EXISTS grades_class_id_idx ON grades(class_id);
CREATE INDEX IF NOT EXISTS student_profiles_class_id_idx ON student_profiles(class_id);
CREATE INDEX IF NOT EXISTS teacher_assignments_teacher_id_idx ON teacher_assignments(teacher_id);
CREATE INDEX IF NOT EXISTS bk_appointments_student_id_idx ON bk_appointments(student_id);
CREATE INDEX IF NOT EXISTS bk_appointments_counselor_id_idx ON bk_appointments(counselor_id);
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);

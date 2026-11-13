-- Seed the standard JALUR high-school class groups for existing schools.
-- Idempotent: safe to apply more than once for the same academic year.
INSERT INTO school_classes (school_id, name, academic_year)
SELECT s.id, levels.level::text || '-' || groups.n::text, '2026/2027'
FROM schools AS s
CROSS JOIN generate_series(10, 12) AS levels(level)
CROSS JOIN generate_series(1, 7) AS groups(n)
ON CONFLICT (school_id, name, academic_year) DO NOTHING;

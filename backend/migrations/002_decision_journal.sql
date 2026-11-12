CREATE TABLE IF NOT EXISTS decision_journal (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  entry_type text NOT NULL,
  program_name text,
  content text NOT NULL CHECK (length(content) BETWEEN 3 AND 12000),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS decision_journal_user_created_idx
  ON decision_journal(user_id, created_at DESC);

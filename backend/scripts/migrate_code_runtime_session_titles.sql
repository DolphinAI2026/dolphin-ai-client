-- Keep an explicit outer-rail title from being replaced by the runtime's
-- first-message fallback title. Run with:
--   python backend/scripts/run_migrations.py backend/scripts/migrate_code_runtime_session_titles.sql

CREATE TABLE IF NOT EXISTS __builder_migrations (
  name VARCHAR(128) NOT NULL PRIMARY KEY,
  applied_at DATETIME NOT NULL
);

ALTER TABLE code_runtime_agent_sessions
  ADD COLUMN title_override BOOLEAN NOT NULL DEFAULT FALSE;

INSERT INTO __builder_migrations (name, applied_at)
SELECT 'migrate_code_runtime_session_titles', NOW()
WHERE NOT EXISTS (
  SELECT 1 FROM __builder_migrations WHERE name = 'migrate_code_runtime_session_titles'
);

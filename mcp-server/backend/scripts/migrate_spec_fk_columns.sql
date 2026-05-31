-- Phase α migration: add spec FK columns to existing tables.
-- Run against dev.db (sqlite) and any prod MySQL DB.
-- Safe to re-run: ALTER guarded with checks where dialect supports it.

-- specs table is auto-created by SQLAlchemy create_all on app startup,
-- but FK columns on existing tables are not added automatically.

-- sqlite (dev.db): no IF NOT EXISTS on ALTER, idempotent via try/catch in shell wrapper
-- MySQL: use IF NOT EXISTS where supported (8.0+)

-- ── For sqlite: run as separate statements, ignore "duplicate column" errors ──
-- Run via: sqlite3 backend/dev.db < backend/scripts/migrate_spec_fk_columns.sql 2>/dev/null || true
ALTER TABLE applications ADD COLUMN canonical_spec_id VARCHAR(40);
ALTER TABLE conversations ADD COLUMN spec_id VARCHAR(40);

-- ── For MySQL 8.0+: ──
-- ALTER TABLE applications ADD COLUMN IF NOT EXISTS canonical_spec_id VARCHAR(40);
-- ALTER TABLE conversations ADD COLUMN IF NOT EXISTS spec_id VARCHAR(40);

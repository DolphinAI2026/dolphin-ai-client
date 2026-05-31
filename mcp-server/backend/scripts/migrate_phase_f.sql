-- Phase F migration：UserPreference 表 + Application.default_mode 列

CREATE TABLE IF NOT EXISTS user_preferences (
  user_id INT NOT NULL PRIMARY KEY,
  default_mode VARCHAR(20) NOT NULL DEFAULT 'simple',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_user_pref_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE applications ADD COLUMN default_mode VARCHAR(20) NULL AFTER status;

INSERT IGNORE INTO __builder_migrations (name, applied_at) VALUES ('migrate_phase_f', NOW());

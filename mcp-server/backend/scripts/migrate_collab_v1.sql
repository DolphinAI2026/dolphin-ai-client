-- 协作 Phase A 迁移：数据模型扩展 + role 命名统一 + 5 张新表
-- 幂等可重跑

-- 0. 迁移记录表（幂等保障）
CREATE TABLE IF NOT EXISTS __builder_migrations (
  name VARCHAR(100) NOT NULL,
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 1. builder_specs 表扩展：kind / commit_sha / version
-- 注意：MySQL 8 不支持 "ADD COLUMN IF NOT EXISTS"。runner 会捕获 errno 1060
-- (Duplicate column) 视为已应用，保证幂等。
ALTER TABLE builder_specs
  ADD COLUMN kind VARCHAR(20) NOT NULL DEFAULT 'draft' AFTER version,
  ADD COLUMN commit_sha VARCHAR(64) NULL AFTER kind;

-- builder_specs.tenant_id 之前默认 1，去掉默认值（先确保无 NULL 值）
UPDATE builder_specs SET tenant_id = 1 WHERE tenant_id IS NULL;
ALTER TABLE builder_specs MODIFY COLUMN tenant_id INT NOT NULL;

-- 2. applications.module_owners JSON nullable
ALTER TABLE applications
  ADD COLUMN module_owners JSON NULL AFTER canonical_spec_id;

-- 3. project_members.role 值迁移：admin → maintainer，member → contributor
UPDATE project_members SET role = 'maintainer' WHERE role = 'admin';
UPDATE project_members SET role = 'contributor' WHERE role = 'member';
-- owner 保持

-- 4. application_members 新建（应用级外部协作者）
CREATE TABLE IF NOT EXISTS application_members (
  id INT NOT NULL AUTO_INCREMENT,
  application_id INT NOT NULL,
  user_id INT NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'contributor',
  invited_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_app_member (application_id, user_id),
  KEY idx_app_member_user (user_id),
  CONSTRAINT fk_app_member_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
  CONSTRAINT fk_app_member_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_app_member_invited FOREIGN KEY (invited_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. change_proposals 空表（Phase B 才会写入数据，先建表）
CREATE TABLE IF NOT EXISTS change_proposals (
  id VARCHAR(40) NOT NULL,
  application_id INT NOT NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT NULL,
  draft_spec_id VARCHAR(40) NOT NULL,
  base_canonical_spec_id VARCHAR(40) NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'draft',
  validation_report JSON NULL,
  apply_plan JSON NULL,
  apply_log JSON NULL,
  git_branch VARCHAR(255) NULL,
  git_pr_url VARCHAR(500) NULL,
  created_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  applied_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_proposal_app_status (application_id, status),
  KEY idx_proposal_draft (draft_spec_id),
  CONSTRAINT fk_proposal_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
  CONSTRAINT fk_proposal_draft FOREIGN KEY (draft_spec_id) REFERENCES builder_specs(id),
  CONSTRAINT fk_proposal_base FOREIGN KEY (base_canonical_spec_id) REFERENCES builder_specs(id),
  CONSTRAINT fk_proposal_created_by FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. proposal_reviews 空表
CREATE TABLE IF NOT EXISTS proposal_reviews (
  id INT NOT NULL AUTO_INCREMENT,
  proposal_id VARCHAR(40) NOT NULL,
  reviewer_id INT NOT NULL,
  action VARCHAR(20) NOT NULL,
  body TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_review_proposal (proposal_id),
  CONSTRAINT fk_review_proposal FOREIGN KEY (proposal_id) REFERENCES change_proposals(id) ON DELETE CASCADE,
  CONSTRAINT fk_review_reviewer FOREIGN KEY (reviewer_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. git_connections 空表（项目级 git 凭证）
CREATE TABLE IF NOT EXISTS git_connections (
  id INT NOT NULL AUTO_INCREMENT,
  project_id INT NOT NULL,
  provider VARCHAR(20) NOT NULL,
  host VARCHAR(255) NOT NULL,
  access_token_enc TEXT NOT NULL,
  group_id_or_org VARCHAR(255) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'connected',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_git_conn_project (project_id),
  CONSTRAINT fk_git_conn_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. platform_drift_logs 空表
CREATE TABLE IF NOT EXISTS platform_drift_logs (
  id INT NOT NULL AUTO_INCREMENT,
  application_id INT NOT NULL,
  detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  git_sha VARCHAR(64) NULL,
  builder_canonical_sha VARCHAR(64) NULL,
  kind VARCHAR(30) NOT NULL,
  resolution_direction VARCHAR(30) NULL,
  resolved_by INT NULL,
  resolved_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_drift_app (application_id),
  CONSTRAINT fk_drift_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
  CONSTRAINT fk_drift_resolved_by FOREIGN KEY (resolved_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9. 标记迁移完成（用于幂等检查）
INSERT IGNORE INTO __builder_migrations (name, applied_at) VALUES ('migrate_collab_v1', NOW());

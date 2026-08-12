-- 标准管理审计日志：MySQL 手工迁移入口，可幂等重跑。

CREATE TABLE IF NOT EXISTS __builder_migrations (
  name VARCHAR(100) NOT NULL,
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_logs (
  id INT NOT NULL AUTO_INCREMENT,
  occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  tenant_id INT NOT NULL,
  application_id INT NULL,
  actor_id INT NULL,
  actor_name VARCHAR(100) NOT NULL,
  event_type VARCHAR(100) NOT NULL,
  target_type VARCHAR(100) NOT NULL,
  target_id VARCHAR(100) NULL,
  result VARCHAR(20) NOT NULL,
  failure_reason TEXT NULL,
  ip_address VARCHAR(64) NULL,
  request_id VARCHAR(100) NULL,
  correlation_id VARCHAR(100) NULL,
  before_value JSON NULL,
  after_value JSON NULL,
  PRIMARY KEY (id),
  KEY idx_audit_logs_tenant_cursor (tenant_id, occurred_at, id),
  KEY idx_audit_logs_application_cursor (application_id, occurred_at, id),
  KEY idx_audit_logs_tenant_event (tenant_id, event_type),
  CONSTRAINT fk_audit_log_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
  CONSTRAINT fk_audit_log_application FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL,
  CONSTRAINT fk_audit_log_actor FOREIGN KEY (actor_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

UPDATE application_members
SET role = CASE
  WHEN role = 'owner' THEN 'owner'
  WHEN role IN ('maintainer', 'admin') THEN 'admin'
  WHEN role IN ('contributor', 'viewer', 'member') THEN 'collaborator'
  ELSE 'collaborator'
END;

ALTER TABLE application_members
  MODIFY COLUMN role VARCHAR(20) NOT NULL DEFAULT 'collaborator';

INSERT IGNORE INTO __builder_migrations (name, applied_at)
VALUES ('migrate_standard_audit_logs', NOW());

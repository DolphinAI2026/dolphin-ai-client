-- 租户级默认 Git 凭证：系统助手和未归属项目的系统资产统一复用。
CREATE TABLE IF NOT EXISTS tenant_git_connections (
  id INT NOT NULL AUTO_INCREMENT,
  tenant_id INT NOT NULL,
  provider VARCHAR(20) NOT NULL,
  host VARCHAR(255) NOT NULL,
  access_token_enc TEXT NOT NULL,
  group_id_or_org VARCHAR(255) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'connected',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_tenant_git_connection (tenant_id),
  CONSTRAINT fk_tenant_git_connection_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO __builder_migrations (name, applied_at) VALUES ('migrate_tenant_git_connection', NOW());

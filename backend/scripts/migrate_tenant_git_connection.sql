-- 租户级默认 Git 凭证：系统助手和未归属项目的系统资产统一复用。
-- 保持 PostgreSQL / MySQL 均可执行；华宝生产库为 PostgreSQL。
CREATE TABLE IF NOT EXISTS __builder_migrations (
  name VARCHAR(255) NOT NULL PRIMARY KEY,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tenant_git_connections (
  -- SERIAL 同时被 PostgreSQL 和 MySQL 接受，且会生成自增主键。
  id SERIAL PRIMARY KEY,
  tenant_id INT NOT NULL,
  provider VARCHAR(20) NOT NULL,
  host VARCHAR(255) NOT NULL,
  access_token_enc TEXT NOT NULL,
  group_id_or_org VARCHAR(255) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'connected',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_tenant_git_connection UNIQUE (tenant_id),
  CONSTRAINT fk_tenant_git_connection_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

INSERT INTO __builder_migrations (name, applied_at)
SELECT 'migrate_tenant_git_connection', CURRENT_TIMESTAMP
WHERE NOT EXISTS (
  SELECT 1 FROM __builder_migrations WHERE name = 'migrate_tenant_git_connection'
);

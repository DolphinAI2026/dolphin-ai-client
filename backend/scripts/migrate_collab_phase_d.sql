-- 协作 Phase D 迁移：GitConnection 加 webhook_secret_enc 列（接收 git 平台 webhook 时验签用）
-- 幂等：runner 把 errno 1060 视为已应用

ALTER TABLE git_connections
  ADD COLUMN webhook_secret_enc TEXT NULL AFTER access_token_enc;

INSERT IGNORE INTO __builder_migrations (name, applied_at) VALUES ('migrate_collab_phase_d', NOW());

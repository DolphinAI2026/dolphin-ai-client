-- 2026-05-09 P3 v3：ai-builder 租户级身份对齐
-- 一个 ai-builder 租户绑定唯一的 apaas 平台环境 + 唯一的 dolphin 租户

START TRANSACTION;

-- 1. 加字段（如果已存在则跳过 — 用 IF NOT EXISTS 兼容）
ALTER TABLE tenants
  ADD COLUMN apaas_env_id INT NULL COMMENT 'ai-builder 租户唯一绑定的 apaas 平台环境 (PlatformEnv.id)',
  ADD COLUMN dolphin_tenant_code VARCHAR(80) NULL COMMENT '该 ai-builder 租户对应的 dolphin 租户 code',
  ADD COLUMN dolphin_tenant_id_str VARCHAR(80) NULL COMMENT 'dolphin 租户的内部 ID（如 default 或长 ID）',
  ADD COLUMN dolphin_agent_code VARCHAR(40) NULL COMMENT '该 ai-builder 租户在 dolphin 平台的 agent code（合并版单 code）';

-- 2. backfill 当前已知的两个租户
-- default 租户(id=1) → dolphin default + 老的 copilot agent（拆分版仍跑）
UPDATE tenants SET
  dolphin_tenant_code = 'default',
  dolphin_tenant_id_str = 'default',
  dolphin_agent_code = '23c93f30d8'
WHERE id = 1;

-- pg 租户(id=5) → dolphin 宝洁租户 + 合并版 agent + apaas env 25（pg 租户的"宝洁"环境）
UPDATE tenants SET
  apaas_env_id = 25,
  dolphin_tenant_code = 'pg',
  dolphin_tenant_id_str = '2048602026513612802',
  dolphin_agent_code = '76b2b8cecc'
WHERE id = 5;

-- 3. verify
SELECT '=== AFTER backfill' AS stage;
SELECT id, tenant_name, tenant_code, apaas_env_id, dolphin_tenant_code, dolphin_tenant_id_str, dolphin_agent_code
FROM tenants
WHERE id IN (1, 5)
ORDER BY id;

COMMIT;

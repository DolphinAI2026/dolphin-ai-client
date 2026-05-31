-- 2026-05-09 P3 v3 修订：dolphin agent code 单字段 → 5 字段
-- 用户决策：copilot / coding / app_adjust / requirements / default 分立
-- 后续每个租户里建合并 agent 时也只用 copilot 字段，其他 NULL fallback 到 copilot

START TRANSACTION;

-- 1. 原 dolphin_agent_code 字段保留作 default fallback，加 4 个分立字段
ALTER TABLE tenants
  ADD COLUMN dolphin_copilot_agent_code VARCHAR(40) NULL COMMENT '应用低代码生命周期 agent (Builder)',
  ADD COLUMN dolphin_coding_agent_code VARCHAR(40) NULL COMMENT '代码态自开发 agent (Coding)',
  ADD COLUMN dolphin_app_adjust_agent_code VARCHAR(40) NULL COMMENT '应用调整 agent (历史遗留)',
  ADD COLUMN dolphin_requirements_agent_code VARCHAR(40) NULL COMMENT '需求分析 agent (历史遗留)';

-- 2. 重置 backfill —— 之前体验租户被合并到单字段 23c93f30d8，现在拆开
-- 体验租户(id=1) → 5 个 .env 默认 agent + apaas_env_id=1 (trial-得帆)
UPDATE tenants SET
  apaas_env_id = 1,
  dolphin_tenant_code = 'default',
  dolphin_tenant_id_str = 'default',
  dolphin_agent_code = 'ad16e01570',
  dolphin_copilot_agent_code = '23c93f30d8',
  dolphin_coding_agent_code = 'f765238af4',
  dolphin_app_adjust_agent_code = 'a73e75cd81',
  dolphin_requirements_agent_code = '2c8be2d99a'
WHERE id = 1;

-- 宝洁(id=5) → 76b2b8cecc 给 copilot；coding 等用户后面建好新 agent 再填
UPDATE tenants SET
  apaas_env_id = 25,
  dolphin_tenant_code = 'pg',
  dolphin_tenant_id_str = '2048602026513612802',
  dolphin_agent_code = NULL,
  dolphin_copilot_agent_code = '76b2b8cecc',
  dolphin_coding_agent_code = NULL,
  dolphin_app_adjust_agent_code = NULL,
  dolphin_requirements_agent_code = NULL
WHERE id = 5;

-- 3. verify
SELECT '=== AFTER backfill' AS stage;
SELECT
  id, tenant_name,
  apaas_env_id,
  dolphin_tenant_code,
  dolphin_copilot_agent_code AS copilot,
  dolphin_coding_agent_code AS coding,
  dolphin_app_adjust_agent_code AS app_adjust,
  dolphin_requirements_agent_code AS requirements,
  dolphin_agent_code AS default_code
FROM tenants
WHERE id IN (1, 5)
ORDER BY id;

COMMIT;

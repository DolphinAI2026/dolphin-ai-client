-- 2026-05-09 阶段1：MCP 工具去耦 ai-builder 用户体系
-- 用户决策：低代码搭建/开发 agent 是独立产品，MCP 工具不该绑死 ai-builder 用户/租户体系。
-- platform_envs 加 alias 字段作为 MCP 工具的全局唯一环境 key——
-- agent 全局记忆只记一行 `env: <alias>`，调工具传 env 字符串就够。
-- 旧 env_id 签名工具通过 deprecated wrapper 兼容（避免线上 dolphin agent 立刻挂）。

START TRANSACTION;

ALTER TABLE platform_envs
  ADD COLUMN alias VARCHAR(50) NULL UNIQUE
    COMMENT 'MCP 工具调用用的全局唯一环境别名（如 dev8/baogong/trial），独立于 ai-builder tenant_id 隔离。NULL 表示未启用新机制（仅老 env_id 工具可用）';

-- backfill 已知 env（按实际线上数据 base_url 比对，2026-05-09 ECS 实测）：
--   id=1  'trial-得帆'    base_url=apaas-trial.definesys.cn/backend  → alias='trial'
--   id=2  'dev环境-得帆'  base_url=apaas-dev8.dfy.definesys.cn/backend → alias='dev8'
-- 注意：id=25 '宝洁' tenant_id=5 实际 base_url 也是 apaas-trial（不是 dev8），
-- alias 留 NULL 让 admin 拍板（如要单独给宝洁分配 alias 可手动 UPDATE alias='baogong'）。
-- 其他 env 留 NULL，admin 后续手动填 alias 才能被新版 MCP 工具使用。
UPDATE platform_envs SET alias = 'trial' WHERE id = 1 AND alias IS NULL;
UPDATE platform_envs SET alias = 'dev8'  WHERE id = 2 AND alias IS NULL;

-- verify
SELECT '=== platform_envs after alias added ===' AS stage;
SELECT id, tenant_id, env_name, alias, base_url, platform_tenant_id, is_default, status
FROM platform_envs
ORDER BY id;

COMMIT;

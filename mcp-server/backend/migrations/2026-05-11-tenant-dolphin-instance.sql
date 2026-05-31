-- 2026-05-11 dolphin instance binding：1:1:1 强绑 ai-builder tenant ↔ apaas env ↔ dolphin (tenant+customer)
-- 用户决策：每个 ai-builder 租户内部强制 1:1:1，dolphin SDK 走官方公开参数
--   { instanceId, customerName, user:{id=apaas_user_id, name} } 替代旧 _jwt/_tenantId 私有路径。
--
-- 不入 DB 的字段：dolphin_instance_id —— 按 agent 产品语义全局固定
--   copilot_agent  → instanceId = "ai-apaas-builder"
--   coding_agent   → instanceId = "ai-apaas-coding"
--   其他 fallback  → instanceId = "ai-apaas-builder"
--   (后端 settings 维护映射常量，需调整时改 .env)

START TRANSACTION;

ALTER TABLE tenants
  ADD COLUMN dolphin_customer_name VARCHAR(128) NULL COMMENT 'dolphin SDK customerName 参数，per-tenant 客户名（如"宝洁（中国）有限公司"）',
  ADD COLUMN dolphin_server_url VARCHAR(255) NULL COMMENT 'dolphin 服务 URL，per-tenant；NULL 则用 .env DOLPHIN_SERVER_URL 兜底';

-- 体验租户（id=1）：内部得帆体验环境
UPDATE tenants SET
  dolphin_customer_name = '得帆体验',
  dolphin_server_url = 'https://dolphin-trial.definesys.cn'
WHERE id = 1;

-- 宝洁（id=2）：dolphin 团队提供的正式客户名
UPDATE tenants SET
  dolphin_customer_name = '宝洁（中国）有限公司',
  dolphin_server_url = 'https://dolphin-trial.definesys.cn'
WHERE id = 2;

-- bkbs(id=3) / deckers(id=4)：孤儿租户，留待平台管理后台补全

-- verify
SELECT
  id, tenant_name, tenant_code,
  apaas_env_id,
  dolphin_tenant_code, dolphin_tenant_id_str,
  dolphin_customer_name, dolphin_server_url,
  dolphin_copilot_agent_code AS copilot,
  dolphin_coding_agent_code AS coding
FROM tenants
ORDER BY id;

COMMIT;

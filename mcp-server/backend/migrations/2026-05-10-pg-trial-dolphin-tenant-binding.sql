-- 2026-05-10: repair PG tenant Dolphin binding without relying on a fixed tenant id.
-- Production has used different ai-builder tenant ids for the PG trial tenant.

START TRANSACTION;

UPDATE tenants
SET
  dolphin_tenant_code = 'pg',
  dolphin_tenant_id_str = '2048602026513612802',
  dolphin_copilot_agent_code = '76b2b8cecc',
  dolphin_coding_agent_code = '41fe6f2479',
  dolphin_app_adjust_agent_code = COALESCE(dolphin_app_adjust_agent_code, '76b2b8cecc'),
  dolphin_requirements_agent_code = COALESCE(dolphin_requirements_agent_code, '76b2b8cecc')
WHERE tenant_code IN ('pg', 'pg_trial')
   OR tenant_name = '宝洁（中国）有限公司';

SELECT
  id,
  tenant_name,
  tenant_code,
  dolphin_tenant_code,
  dolphin_tenant_id_str,
  dolphin_copilot_agent_code,
  dolphin_coding_agent_code
FROM tenants
WHERE tenant_code IN ('pg', 'pg_trial')
   OR tenant_name = '宝洁（中国）有限公司';

COMMIT;

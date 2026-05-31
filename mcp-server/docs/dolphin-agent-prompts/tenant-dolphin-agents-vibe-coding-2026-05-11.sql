-- 2026-05-11 加 Vibe Coding 智能体到 tenant_dolphin_agents 表
-- 跑前先在 dolphin admin 新建 AI-aPaaS-Vibe 智能体拿到 agent_code，
-- 然后用 sed 替换 <AGENT_CODE_HERE>。
--
-- 每个 tenant 一行；NavRail 入口动态拉本表渲染（参见 routes/tenant_dolphin_agents.py + BuilderNavRail.vue）
--
-- 字段类型实测（2026-05-11 ECS schema）：
--   status   tinyint NOT NULL DEFAULT 1（1=active 0=disabled）— ✗ 不是 varchar('active')
--   is_default tinyint(1) NOT NULL DEFAULT 0
--   created_at / updated_at — DEFAULT CURRENT_TIMESTAMP，不必传
--
-- 实测 ECS 生产 tenants id 映射：
--   1=default / 2=pg_trial / 3=bkbs / 4=deckers / 6=definesys
--   （本机老快照里 self_xx 测试租户排序不同 — 跑前确认 SELECT id, tenant_code FROM tenants）

INSERT INTO tenant_dolphin_agents (
  tenant_id, agent_code, instance_id, display_name,
  nav_path, nav_icon, sort_order, button_text,
  is_default, status
) VALUES
  (1, '<AGENT_CODE_HERE>', 'ai-apaas-vibe', 'Vibe Coding', '/agent/vibe-coding', 'Box', 30, '🧪 Vibe Coding', 0, 1),
  (2, '<AGENT_CODE_HERE>', 'ai-apaas-vibe', 'Vibe Coding', '/agent/vibe-coding', 'Box', 30, '🧪 Vibe Coding', 0, 1);
  -- 后续如要给 bkbs / deckers / definesys 也加，复制一行改 tenant_id 即可

-- 验证插入成功 + 看 default 租户全部 agent 排序
SELECT
  id, tenant_id, agent_code, instance_id, display_name, nav_path, sort_order, button_text, is_default, status
FROM tenant_dolphin_agents
WHERE tenant_id IN (1, 5)
ORDER BY tenant_id, sort_order;

-- 注意：
-- 1. dolphin admin 上 agent 可以是同一个 agent_code 在多个 tenant 共享（trial 环境单 agent 公开就行）
--    也可以每个 tenant 一个独立 agent_code（隔离更彻底）
-- 2. 跑完 SQL 后 ai-builder NavRail 会自动拉新入口，**用户硬刷一次浏览器**（Cmd+Shift+R）才能看到
-- 3. 用户点 NavRail 的 "🧪 Vibe Coding" → 进 /agent/vibe-coding catch-all 路由 → AgentEmbedPage.vue → dolphin SDK 浮窗会自动加载 agent_code 对应的 Vibe agent

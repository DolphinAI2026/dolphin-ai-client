-- 2026-05-11 第二轮：dolphin agent 配置升级为 per-tenant N 行表
--
-- 用户决策：(1) dolphin agent 配置搬出 tenants 表，做成租户管理员可在「设置 > 平台环境」维护的独立实体；
--           (2) NavRail 入口从硬编码改为按本表 nav_path 字段动态渲染。
--
-- 现状 tenants 表 5 列（copilot/coding/app_adjust/requirements/default）拆出 → 新表 N 行，
-- 每行 = (agent_code, instance_id, display_name, nav_path, ...) 完整 agent 入口配置。
-- 兼容期 tenants 旧字段保留（不 drop），等所有读写都切到新表后再清理。

START TRANSACTION;

CREATE TABLE IF NOT EXISTS tenant_dolphin_agents (
  id INT PRIMARY KEY AUTO_INCREMENT,
  tenant_id INT NOT NULL COMMENT '所属 ai-builder 租户',
  agent_code VARCHAR(40) NOT NULL COMMENT 'dolphin agent code',
  instance_id VARCHAR(80) NOT NULL COMMENT 'dolphin SDK instanceId（产品维度，如 ai-apaas-builder / ai-apaas-coding / 客户自起）',
  display_name VARCHAR(64) NOT NULL COMMENT '展示名（NavRail 入口标题 + 平台环境列表标题）',
  description VARCHAR(255) NULL COMMENT '说明文案，可选',
  nav_path VARCHAR(64) NULL COMMENT '留空=不在 NavRail 显示；填了=NavRail 入口路径 /agent/{path}',
  nav_icon VARCHAR(32) NULL COMMENT 'el-icon 或 lucide 图标名',
  sort_order INT NOT NULL DEFAULT 100 COMMENT 'NavRail / 列表排序，升序',
  button_text VARCHAR(64) NULL COMMENT '浮窗按钮文案（dolphin SDK buttonText 参数）',
  is_default TINYINT(1) NOT NULL DEFAULT 0 COMMENT '该 tenant 默认浮窗 agent（HelpAssistant 用，仅一行可为 1）',
  status TINYINT NOT NULL DEFAULT 1 COMMENT '1=启用 / 0=禁用',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tenant_agent (tenant_id, agent_code),
  KEY idx_tenant_nav (tenant_id, status, sort_order),
  CONSTRAINT fk_tenant_dolphin_agents_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='dolphin agent 入口表，per-tenant N 行；NavRail 入口 + 浮窗 + 嵌入式 chat 都从这查';

-- 数据迁移：从 tenants 表 5 列搬到 N 行
-- tenant 1（体验租户）→ 5 行
INSERT INTO tenant_dolphin_agents
  (tenant_id, agent_code, instance_id, display_name, description, nav_path, nav_icon, sort_order, button_text, is_default, status)
VALUES
  (1, '23c93f30d8', 'ai-apaas-builder', '智能搭建',     '应用低代码生命周期 — 一句话生成可上线应用',
   '/ai-copilot',  'Robot',  10,  'AI-aPaaS-Builder', 1, 1),
  (1, 'f765238af4', 'ai-apaas-coding',  '低代码自开发', '组件 / 页面 / 接口 — 代码态自开发',
   '/ai-coding',   'CodeBracket', 20,  'AI-aPaaS-Coding', 0, 1),
  (1, 'a73e75cd81', 'ai-apaas-builder', '应用调整助手', '老路径 — 应用详情页 AI 调整功能',
   NULL,           NULL, 90,  NULL,                0, 1),
  (1, '2c8be2d99a', 'ai-apaas-builder', '需求分析助手', '老路径 — 已并入智能搭建',
   NULL,           NULL, 91,  NULL,                0, 1),
  (1, 'ad16e01570', 'ai-apaas-builder', 'AI-Builder 助手', '通用浮窗 — 老路径',
   NULL,           NULL, 99,  NULL,                0, 1);

-- tenant 2（宝洁中国）→ 2 行
INSERT INTO tenant_dolphin_agents
  (tenant_id, agent_code, instance_id, display_name, description, nav_path, nav_icon, sort_order, button_text, is_default, status)
VALUES
  (2, '76b2b8cecc', 'ai-apaas-builder', '智能搭建',     '应用低代码生命周期（宝洁定制）',
   '/ai-copilot',  'Robot',  10,  'AI-aPaaS-Builder', 1, 1),
  (2, '41fe6f2479', 'ai-apaas-coding',  '低代码自开发', '组件 / 页面 / 接口（宝洁定制）',
   '/ai-coding',   'CodeBracket', 20,  'AI-aPaaS-Coding', 0, 1);

-- tenant 3 (bkbs) / 4 (deckers) 仍为孤儿，本表无记录，admin 自助补全

-- verify
SELECT '=== 迁移结果 ===' AS info;
SELECT
  t.id AS tenant_id, t.tenant_code,
  COUNT(a.id) AS agent_rows,
  SUM(CASE WHEN a.nav_path IS NOT NULL THEN 1 ELSE 0 END) AS nav_entries,
  SUM(CASE WHEN a.is_default = 1 THEN 1 ELSE 0 END) AS default_count
FROM tenants t
LEFT JOIN tenant_dolphin_agents a ON a.tenant_id = t.id AND a.status = 1
GROUP BY t.id, t.tenant_code
ORDER BY t.id;

SELECT '=== tenant 1 详细 ===' AS info;
SELECT id, agent_code, instance_id, display_name, nav_path, sort_order, is_default
FROM tenant_dolphin_agents WHERE tenant_id = 1 ORDER BY sort_order;

SELECT '=== tenant 2 详细 ===' AS info;
SELECT id, agent_code, instance_id, display_name, nav_path, sort_order, is_default
FROM tenant_dolphin_agents WHERE tenant_id = 2 ORDER BY sort_order;

COMMIT;

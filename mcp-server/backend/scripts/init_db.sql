-- ============================================================
-- aPaaS Builder AI 数据库初始化脚本 (MySQL 8.0+)
--
-- 使用方法：
--   1. 创建数据库：CREATE DATABASE apaas_builder CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
--   2. 执行此脚本：mysql -u root -p apaas_builder < init_db.sql
--   3. 修改 backend/.env 中的 DATABASE_URL
-- ============================================================

-- -----------------------------------------------------------
-- 1. 租户表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_name VARCHAR(128) NOT NULL,
    tenant_code VARCHAR(64) NOT NULL,
    plan_type VARCHAR(32) NOT NULL DEFAULT 'free' COMMENT 'free/pro/enterprise',
    max_applications INT NOT NULL DEFAULT 10,
    status INT NOT NULL DEFAULT 1 COMMENT '1=active, 0=disabled',
    contact_name VARCHAR(64) DEFAULT NULL,
    contact_email VARCHAR(128) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_tenant_code (tenant_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 2. 用户表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    apaas_token TEXT DEFAULT NULL COMMENT '得帆云平台登录 token',
    apaas_user_id VARCHAR(50) DEFAULT NULL,
    apaas_base_url VARCHAR(255) DEFAULT NULL COMMENT '得帆云平台地址',
    apaas_tenant_id VARCHAR(50) DEFAULT NULL COMMENT '得帆云租户ID',
    is_platform_admin TINYINT(1) NOT NULL DEFAULT 0,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 3. 角色表（租户隔离）
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id INT NOT NULL,
    role_name VARCHAR(64) NOT NULL,
    role_code VARCHAR(64) NOT NULL,
    description TEXT DEFAULT NULL,
    permissions JSON NOT NULL COMMENT '{"application:create": true, ...}',
    is_system TINYINT(1) NOT NULL DEFAULT 0 COMMENT '系统角色不可删除',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_tenant_role_code (tenant_id, role_code),
    KEY idx_roles_tenant (tenant_id),
    CONSTRAINT fk_roles_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 4. 用户-租户关系表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_tenants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    tenant_id INT NOT NULL,
    role_id INT DEFAULT NULL,
    is_default TINYINT(1) NOT NULL DEFAULT 1,
    status INT NOT NULL DEFAULT 1 COMMENT '1=active, 0=disabled',
    joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_tenant (user_id, tenant_id),
    KEY idx_ut_user (user_id),
    KEY idx_ut_tenant (tenant_id),
    CONSTRAINT fk_ut_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_ut_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT fk_ut_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 5. 团队表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id INT NOT NULL,
    team_name VARCHAR(128) NOT NULL,
    description TEXT DEFAULT NULL,
    status INT NOT NULL DEFAULT 1,
    created_by INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_team_tenant_name (tenant_id, team_name),
    KEY idx_teams_tenant (tenant_id),
    CONSTRAINT fk_teams_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 6. 团队成员表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_members (
    id INT AUTO_INCREMENT PRIMARY KEY,
    team_id INT NOT NULL,
    user_id INT NOT NULL,
    team_role VARCHAR(32) NOT NULL DEFAULT 'member' COMMENT 'admin/member/viewer',
    joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_team_member (team_id, user_id),
    KEY idx_tm_team (team_id),
    KEY idx_tm_user (user_id),
    CONSTRAINT fk_tm_team FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
    CONSTRAINT fk_tm_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 7. 对话表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    tenant_id INT NOT NULL,
    title VARCHAR(200) NOT NULL,
    agent_type VARCHAR(20) NOT NULL COMMENT 'builder/assistant/developer',
    status VARCHAR(20) NOT NULL DEFAULT 'active' COMMENT 'active/completed/failed',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_conv_user (user_id),
    KEY idx_conv_tenant (tenant_id),
    CONSTRAINT fk_conv_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 8. 消息表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    conversation_id INT NOT NULL,
    role VARCHAR(20) NOT NULL COMMENT 'user/assistant/system',
    content TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_msg_conv (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 9. 应用表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS applications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    tenant_id INT NOT NULL,
    team_id INT DEFAULT NULL,
    created_by INT NOT NULL,
    conversation_id INT NOT NULL,
    apaas_app_id VARCHAR(50) DEFAULT NULL COMMENT '得帆云平台应用ID',
    app_name VARCHAR(100) NOT NULL,
    app_code VARCHAR(50) NOT NULL,
    description TEXT DEFAULT NULL,
    requirement_doc TEXT DEFAULT NULL COMMENT 'JSON: 需求文档',
    config_preview TEXT DEFAULT NULL COMMENT 'JSON: 应用配置预览',
    generation_state TEXT DEFAULT NULL COMMENT 'JSON: Copilot 分步部署中间状态',
    status VARCHAR(20) NOT NULL DEFAULT 'draft' COMMENT 'draft/generating/completed/failed',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_app_user (user_id),
    KEY idx_app_tenant (tenant_id),
    KEY idx_app_team (team_id),
    KEY idx_app_created_by (created_by),
    KEY idx_app_conv (conversation_id),
    CONSTRAINT fk_app_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    CONSTRAINT fk_app_team FOREIGN KEY (team_id) REFERENCES teams(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- 10. 初始化种子数据
-- -----------------------------------------------------------

-- 默认租户
INSERT INTO tenants (tenant_name, tenant_code, plan_type, max_applications, status)
VALUES ('Default Tenant', 'default', 'free', 100, 1)
ON DUPLICATE KEY UPDATE tenant_name = tenant_name;

-- 默认管理员角色（完整权限）
INSERT INTO roles (tenant_id, role_name, role_code, permissions, is_system)
SELECT t.id, 'Admin', 'admin', '{"application:view":true,"application:create":true,"application:edit":true,"application:delete":true,"application:clone":true,"conversation:view":true,"conversation:create":true,"conversation:delete":true,"team:view":true,"team:create":true,"team:manage":true,"member:view":true,"member:invite":true,"member:manage":true,"role:view":true,"role:create":true,"role:edit":true,"role:delete":true}', 1
FROM tenants t WHERE t.tenant_code = 'default'
ON DUPLICATE KEY UPDATE role_name = role_name;

-- 默认普通用户角色（基础权限）
INSERT INTO roles (tenant_id, role_name, role_code, permissions, is_system)
SELECT t.id, 'Member', 'member', '{"application:view":true,"application:create":true,"application:edit":true,"application:delete":true,"application:clone":true,"conversation:view":true,"conversation:create":true,"conversation:delete":true,"team:view":true}', 0
FROM tenants t WHERE t.tenant_code = 'default'
ON DUPLICATE KEY UPDATE role_name = role_name;

-- ============================================================
-- 完成！
--
-- 接下来：
-- 1. 复制 backend/.env.example → backend/.env
-- 2. 修改 DATABASE_URL 为：
--    mysql+aiomysql://用户名:密码@localhost:3306/apaas_builder
-- 3. 修改 LLM_API_KEY 为你的 API Key
-- 4. 启动后端：cd backend && python run.py
-- 5. 启动前端：cd frontend && npm install && npm run dev
-- 6. 访问 http://localhost:5173 注册账号
-- ============================================================

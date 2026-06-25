-- 代码会话工作区 ↔ git 远程仓绑定表
-- 模型 B：工作区级，一个工作区绑定一个远程仓
-- 凭证复用 git_connections.id（加密 PAT）

CREATE TABLE IF NOT EXISTS workspace_git_remote (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    ws_id VARCHAR(64) NOT NULL UNIQUE COMMENT '工作区ID，唯一',
    tenant_id INT NOT NULL COMMENT '租户ID',
    user_id INT NOT NULL COMMENT '用户ID',
    provider VARCHAR(20) NOT NULL COMMENT 'git 提供商 (gitlab/github)',
    remote_url VARCHAR(500) NOT NULL COMMENT '远程仓库 URL (https://...)',
    default_branch VARCHAR(120) COMMENT '远程默认分支（可空）',
    git_connection_id INT NOT NULL COMMENT '对应 git_connections.id（凭证引用）',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_user_id (user_id),
    INDEX idx_ws_id (ws_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

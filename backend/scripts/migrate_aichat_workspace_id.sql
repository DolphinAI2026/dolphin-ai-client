-- 2026-06-25 给 ai_chat_sessions 加 workspace_id 列(SP2a 地基)
--
-- Code 会话(mode='code')把绑定的工作区 ws_id 落到这一列,供统一引擎
-- run_agent 在调用方未传 override 时按 session.mode 推导 dev-apaas 行为 +
-- 单工作区锁(_locked_ws_id)。注意:这是 WorkspaceManager 的 ws_id,
-- 不是 workspace_dir 那个文件系统路径。
--
-- 幂等:run_migrations.py 把 MySQL errno 1060(列已存在)当成功跳过。
--
-- 运行方式:
--   python scripts/run_migrations.py scripts/migrate_aichat_workspace_id.sql

ALTER TABLE ai_chat_sessions ADD COLUMN workspace_id VARCHAR(64) NULL;

-- 模型声明 index=True;补索引让生产与 ORM 一致(errno 1061=索引已存在时跳过)。
CREATE INDEX ix_ai_chat_sessions_workspace_id ON ai_chat_sessions (workspace_id);

-- 协作 Phase C 迁移：applications 增加 git 镜像元数据列
-- 幂等：runner 把 errno 1060 (Duplicate column) 视为已应用

ALTER TABLE applications
  ADD COLUMN git_repo_url VARCHAR(500) NULL AFTER status,
  ADD COLUMN git_provider VARCHAR(20) NULL AFTER git_repo_url,
  ADD COLUMN git_default_branch VARCHAR(100) NULL AFTER git_provider;

-- 标记迁移完成
INSERT IGNORE INTO __builder_migrations (name, applied_at) VALUES ('migrate_collab_phase_c', NOW());

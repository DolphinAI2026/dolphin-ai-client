-- 2026-05-27 SPEC 版本快照 + markdown 缓存
--
-- Y 阶段: 给"确认并生成"加生产级版本管理.
--   - spec_applied_versions: 每次 apply 后的 frozen 快照 (N 行 per app)
--   - spec_documents: 当前 SPEC.md 缓存 (1 行 per app, upsert)
--
-- 注: backend 启动时 Base.metadata.create_all 会自动按 SQLAlchemy model 建表
-- (database.py:init_db). 本文件给生产 MySQL 直接执行 / audit / rollback 用.
--
-- 运行方式 (mysql-only, sqlite dev.db 自动 create_all 不用跑):
--   python scripts/run_migrations.py scripts/migrate_spec_versions_2026_05_27.sql

CREATE TABLE IF NOT EXISTS spec_applied_versions (
    id              INT NOT NULL AUTO_INCREMENT,
    application_id  INT NOT NULL,
    version_label   VARCHAR(32) NOT NULL,
    applied_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_by_user_id INT NOT NULL,
    -- 整 SPEC 快照 (sections + meta + captured_at)
    sections_snapshot JSON NOT NULL,
    -- markdown_snapshot 整渲染后的 SPEC.md, 应用 dict + 大 list 时可能 >64KB
    markdown_snapshot LONGTEXT NULL,
    -- MCP 执行统计
    total_steps     INT NOT NULL DEFAULT 0,
    applied_steps   INT NOT NULL DEFAULT 0,
    failed_steps    INT NOT NULL DEFAULT 0,
    -- 每 step 详情 (apply_results) — 跟 SpecApply API 返一致
    apply_results   JSON NULL,
    -- is_active: 只最新成功 apply 行 = true (per app), 失败行 = false 审计用
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id),
    CONSTRAINT fk_spec_app_ver_app
        FOREIGN KEY (application_id) REFERENCES applications(id),
    KEY ix_spec_app_ver_app (application_id),
    KEY ix_spec_app_ver_active (is_active),
    KEY ix_spec_app_ver (application_id, applied_at)
);

CREATE TABLE IF NOT EXISTS spec_documents (
    id              INT NOT NULL AUTO_INCREMENT,
    application_id  INT NOT NULL,
    markdown_content LONGTEXT NOT NULL,
    last_generated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- sha256 of sections JSON — 用来判断 cache 是否还 fresh
    sections_hash   VARCHAR(64) NOT NULL DEFAULT '',
    PRIMARY KEY (id),
    UNIQUE KEY uq_spec_doc_app (application_id),
    CONSTRAINT fk_spec_doc_app
        FOREIGN KEY (application_id) REFERENCES applications(id)
);

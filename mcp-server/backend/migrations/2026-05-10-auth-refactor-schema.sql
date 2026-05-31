-- =====================================================================
-- Auth Refactor — Phase 1 Schema Migration
-- 2026-05-10
--
-- 目标：让 users.apaas_user_id / tenants.apaas_tenant_id_str 成为可信的
--       跨系统映射键，为 token exchange 端点 + 双 ID JWT 做基础。
--
-- 设计原则：
--   - 加列 + 加索引，不动现有 FK 和数据
--   - apaas_user_id 保留 NULL（允许 local-only 用户）；UNIQUE 但允许多 NULL
--     （MySQL 8.x B-Tree UNIQUE 标准行为）
--   - tenants.apaas_tenant_id_str UNIQUE，同样允许 NULL（default tenant 不强绑）
--   - 加列前先 SELECT 实测无重复（已 Phase 0 audit 过：0 dups）
--
-- 适用 DB 引擎：MySQL 8.0+
-- 跑前先 backup：
--   mysqldump -uapaas -papaas2024 apaas_builder users tenants > /root/db-backup-2026-05-10.sql
-- =====================================================================

-- ── 1. users.apaas_user_id 加 UNIQUE INDEX ────────────────────────────
-- 现状：String(50) nullable，无索引。MySQL UNIQUE 允许多个 NULL。
ALTER TABLE users
  ADD UNIQUE INDEX uq_users_apaas_uid (apaas_user_id);

-- ── 2. tenants 加 apaas_tenant_id_str 列 + UNIQUE ────────────────────
-- 现状：Tenant 模型只有 dolphin_tenant_id_str（dolphin 那一边），缺 apaas 一边。
-- 加完后：
--   default tenant     → NULL（多环境 探索租户）
--   pg_trial           → '833850449709760513'（强绑宝洁 apaas tenant）
ALTER TABLE tenants
  ADD COLUMN apaas_tenant_id_str VARCHAR(40) NULL
    COMMENT 'aPaaS 平台租户 21 位 bigint string；NULL=该 ai-builder 租户不强绑单一 apaas tenant',
  ADD UNIQUE INDEX uq_tenants_apaas_tid (apaas_tenant_id_str);

-- ── 3. 数据回填：tenants.apaas_tenant_id_str ─────────────────────────
-- pg_trial 已绑 baogong env (alias=baogong, platform_tenant_id=833850449709760513)
UPDATE tenants
SET apaas_tenant_id_str = '833850449709760513'
WHERE tenant_code = 'pg_trial';

-- default tenant 多环境探索，保留 NULL
-- bkbs / deckers 当前未绑 apaas，保留 NULL（admin 后续按需手动绑）

-- ── 4. users.apaas_user_id 数据回填 ─────────────────────────────────
-- 由 backend/scripts/backfill_apaas_user_id.py 执行，不在 SQL 里硬编码。
-- 脚本会：
--   1. 用 admin token 登 apaas_trial（pg_trial env 用同 apaas_trial host）
--   2. 切到目标 apaas tenant context
--   3. 调 /xdap-app/user/select/queryAllUsers 拿全量 [{id, account}]
--   4. ai-builder users.username == apaas account 匹配 → UPDATE apaas_user_id

-- ── 5. 验证 SQL（迁移完跑一遍）────────────────────────────────────
-- SELECT '后置校验' AS s;
-- SELECT COUNT(*) AS users_with_apaas_uid FROM users WHERE apaas_user_id IS NOT NULL;
-- SELECT COUNT(DISTINCT apaas_user_id) AS distinct_uid FROM users WHERE apaas_user_id IS NOT NULL;
-- SELECT id, tenant_code, apaas_tenant_id_str FROM tenants ORDER BY id;

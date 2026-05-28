-- 2026-05-28 给 spec_documents 加 parsed_sections_json 列
--
-- 之前只缓存 markdown 输出, panel 渲染时 8 个 /section-content/* 还是要并发打
-- apaas. 这次把 generator 一次拉的全 11 章 raw data 也存进 DB, 让 panel reload
-- 1 个 endpoint /spec/parsed 拿全数据. backend 重启不丢, 秒级命中.
--
-- 跟 markdown_content 同生命周期: 同生成 + 同失效 (spec_apply 后置空触发重生).
--
-- 三步走避开 MySQL "TEXT/BLOB 不能有 inline DEFAULT" 限制 (8.0.13 前):
-- 1. 先加可空列
-- 2. 给老行回填 '{}'
-- 3. 改成 NOT NULL
--
-- 运行方式:
--   python scripts/run_migrations.py scripts/migrate_spec_parsed_sections_2026_05_28.sql

ALTER TABLE spec_documents ADD COLUMN parsed_sections_json LONGTEXT NULL;

UPDATE spec_documents SET parsed_sections_json = '{}' WHERE parsed_sections_json IS NULL;

ALTER TABLE spec_documents MODIFY COLUMN parsed_sections_json LONGTEXT NOT NULL;

<!-- frontend/src/views/v2/SpecsPage.vue -->
<!--
  Seed data until backend `api/specs.ts` exists. Backend SPEC versioning is
  out-of-scope for the P0+P1 plan — this page renders local seed so that
  the sidebar entry never 404s and design review can validate the layout.
  See docs/superpowers/plans/2026-05-18-apaas-builder-redesign-p0-p1.md
  (Task 6.1).
-->
<script setup lang="ts">
import { ref } from 'vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'

interface SpecVersion {
  v: number
  status: 'draft' | 'test' | 'prod' | 'archived'
  note: string
  author: string
  date: string
}
interface Spec {
  id: string
  appName: string
  latest: number
  diff: { add: number; mod: number }
  origin: string
  versions: SpecVersion[]
  sections: { name: string; count: number }[]
  excerpt: string
}

const specs = ref<Spec[]>([
  {
    id: 's1',
    appName: '资产管理系统',
    latest: 3,
    diff: { add: 2, mod: 4 },
    origin: '基于 标准模板 + 制造装备包 v2.1',
    versions: [
      { v: 3, status: 'draft', note: '加保修截止日期 / 采购来源', author: 'mars', date: '2026-05-18' },
      { v: 2, status: 'test', note: '加财务审批分支', author: 'mars', date: '2026-05-15' },
      { v: 1, status: 'prod', note: '首版上线', author: '陈青羽', date: '2026-05-08' },
      { v: 0, status: 'archived', note: '初稿（已归档）', author: 'mars', date: '2026-05-02' },
    ],
    sections: [
      { name: '需求摘要', count: 1 },
      { name: '数据模型', count: 6 },
      { name: '表单', count: 6 },
      { name: '流程', count: 2 },
      { name: '角色权限', count: 3 },
      { name: '字典', count: 6 },
    ],
    excerpt:
      '| 字段 | 类型 | 必填 | 备注 |\n|---|---|---|---|\n| 资产名称 | String(120) | 是 | |\n| 保修截止 | Date | 否 | NEW |',
  },
])
const selected = ref<Spec | null>(specs.value[0])

const ORIGIN_STEPS = ['标准模板', '行业知识库', '睿鲸 AI Builder 对话产出', '部署到 aPaaS 平台']
const statusBadgeClass: Record<string, string> = {
  draft: 'badge-amber',
  test: 'badge-sky',
  prod: 'badge-emerald',
  archived: 'badge-outline',
}
const statusLabel: Record<string, string> = {
  draft: '草稿',
  test: '已部署测试',
  prod: '已部署生产',
  archived: '归档',
}
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="page">
      <div class="page-pad">
        <div class="page-head">
          <div>
            <h1 class="page-title">设计文档</h1>
            <div class="page-subtitle">每个应用一份多版本 SPEC，版本时间线决定环境部署与回滚。</div>
          </div>
        </div>
        <div class="origin-strip">
          <span v-for="(s, i) in ORIGIN_STEPS" :key="s">
            <span class="origin-step">{{ s }}</span>
            <span v-if="i < ORIGIN_STEPS.length - 1" class="origin-arrow">→</span>
          </span>
        </div>

        <div class="specs-layout">
          <aside class="specs-list">
            <button
              v-for="s in specs"
              :key="s.id"
              class="spec-row"
              :class="{ active: selected?.id === s.id }"
              @click="selected = s"
            >
              <div class="spec-row-name">{{ s.appName }}</div>
              <div class="spec-row-meta">
                <span class="badge badge-brand">v{{ s.latest }}</span>
                <span class="badge badge-emerald">+{{ s.diff.add }}</span>
                <span class="badge badge-amber">~{{ s.diff.mod }}</span>
              </div>
              <div class="spec-row-origin">{{ s.origin }}</div>
            </button>
          </aside>

          <main class="spec-detail" v-if="selected">
            <div class="card card-pad">
              <div class="spec-head">
                <div>
                  <div class="spec-head-app">{{ selected.appName }}</div>
                  <div class="spec-head-sub">最新 v{{ selected.latest }} · {{ selected.origin }}</div>
                </div>
                <div class="spec-head-actions">
                  <button class="btn btn-secondary btn-sm">导出 .md</button>
                  <button class="btn btn-secondary btn-sm">在 Builder 打开</button>
                  <button class="btn btn-primary btn-sm">基于此部署</button>
                </div>
              </div>

              <div class="section-head"><div class="section-title">版本时间线</div></div>
              <ol class="versions">
                <li v-for="v in selected.versions" :key="v.v" :class="v.status">
                  <div class="ver-dot" />
                  <div class="ver-body">
                    <div>
                      <b>v{{ v.v }}</b>
                      <span class="badge" :class="statusBadgeClass[v.status]">{{ statusLabel[v.status] }}</span>
                    </div>
                    <div class="ver-note">{{ v.note }}</div>
                    <div class="ver-meta mono">{{ v.author }} · {{ v.date }}</div>
                  </div>
                </li>
              </ol>

              <div class="section-head"><div class="section-title">章节</div></div>
              <div class="spec-sections-grid">
                <div v-for="sec in selected.sections" :key="sec.name" class="spec-section-card">
                  <div class="spec-section-name">{{ sec.name }}</div>
                  <div class="spec-section-count">{{ sec.count }}</div>
                </div>
              </div>

              <div class="section-head"><div class="section-title">Markdown 摘录</div></div>
              <pre class="md-excerpt"><code>{{ selected.excerpt }}</code></pre>
            </div>
          </main>
        </div>
      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; flex: 1; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { margin-bottom: 14px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; }
.origin-strip { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; font-size: 12px; color: var(--text-2); margin-bottom: 18px; }
.origin-step { padding: 4px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; }
.origin-arrow { color: var(--text-4); margin: 0 4px; }
.specs-layout { display: grid; grid-template-columns: 320px 1fr; gap: 18px; align-items: flex-start; }
.specs-list { display: flex; flex-direction: column; gap: 8px; }
.spec-row { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; text-align: left; cursor: pointer; font-family: inherit; color: var(--text); transition: border-color 0.14s, box-shadow 0.14s; }
.spec-row:hover { border-color: var(--border-strong); }
.spec-row.active { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }
.spec-row-name { font-size: 13.5px; font-weight: 600; }
.spec-row-meta { display: flex; gap: 4px; margin-top: 6px; }
.spec-row-origin { font-size: 11px; color: var(--text-3); margin-top: 6px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); }
.card-pad { padding: 18px; }
.spec-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.spec-head-app { font-size: 17px; font-weight: 600; color: var(--text); letter-spacing: -0.01em; }
.spec-head-sub { font-size: 12px; color: var(--text-3); margin-top: 3px; }
.spec-head-actions { display: flex; gap: 6px; }
.btn { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit; }
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-secondary { background: var(--surface); border-color: var(--border-strong); }
.section-head { margin: 16px 0 8px; }
.section-title { font-size: 13px; font-weight: 600; color: var(--text); }
.versions { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 12px; }
.versions li { display: flex; gap: 12px; align-items: flex-start; padding: 8px 4px; }
.ver-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--surface-3); border: 2px solid var(--border-strong); flex-shrink: 0; margin-top: 5px; }
.versions li.draft .ver-dot { background: var(--amber); border-color: var(--amber); animation: pulse 1.6s infinite; }
.versions li.test .ver-dot { background: var(--sky); border-color: var(--sky); }
.versions li.prod .ver-dot { background: var(--emerald); border-color: var(--emerald); }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 var(--amber-bg); } 50% { box-shadow: 0 0 0 8px transparent; } }
.ver-body { font-size: 13px; }
.ver-note { color: var(--text-2); margin-top: 2px; }
.ver-meta { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.spec-sections-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.spec-section-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.spec-section-name { font-size: 12px; color: var(--text-2); }
.spec-section-count { font-size: 17px; font-weight: 600; color: var(--text); letter-spacing: -0.01em; margin-top: 2px; }
.md-excerpt { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; overflow-x: auto; color: var(--code-text); font-family: var(--d-font-mono); font-size: 11.5px; line-height: 1.5; }
.badge { display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border-radius: 5px; font-size: 11px; font-weight: 500; background: var(--surface-3); color: var(--text-2); border: 1px solid transparent; margin-left: 6px; }
.spec-row-meta .badge { margin-left: 0; }
.badge-brand { background: var(--brand-soft); color: var(--brand-text); }
.badge-emerald { background: var(--emerald-bg); color: var(--emerald); }
.badge-amber { background: var(--amber-bg); color: var(--amber); }
.badge-sky { background: var(--sky-bg); color: var(--sky); }
.badge-outline { background: transparent; border-color: var(--border-strong); }
.mono { font-family: var(--d-font-mono); }
</style>

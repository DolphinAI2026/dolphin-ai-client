<!-- frontend/src/views/v2/SpecsPage.vue -->
<!--
  Wired to /api/specs-v2 — one synthetic v1 SPEC per Application in the
  tenant. Real multi-version + diff comes in a follow-up. Backend route:
  backend/app/routes/specs_v2.py.
-->
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'
import { useSpecsV2Store } from '@/stores/specsV2'
import type { SpecListItem } from '@/api/specsV2'

const store = useSpecsV2Store()
const selectedId = ref<string | null>(null)

onMounted(async () => {
  await store.fetchSpecs()
})

// Keep selected pinned to the first spec by default; user can change.
watch(
  () => store.specs,
  (next) => {
    if (!selectedId.value && next.length > 0) selectedId.value = next[0].id
  },
  { immediate: true },
)

const selected = computed<SpecListItem | null>(() => {
  if (!selectedId.value) return store.specs[0] ?? null
  return store.specs.find(s => s.id === selectedId.value) ?? (store.specs[0] ?? null)
})

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

/** doc_type chip — 标在 SPEC head 的应用名旁边，让用户立刻看出"这是 SPEC 还是别的"。 */
const docTypeLabel: Record<string, string> = {
  spec: '📐 SPEC 标准设计',
  self_dev_package: '📦 自开发包',
  page_design: '🎨 页面设计',
  general: '📄 通用文档',
}
const docTypeBadgeClass: Record<string, string> = {
  spec: 'badge-brand',
  self_dev_package: 'badge-amber',
  page_design: 'badge-sky',
  general: 'badge-outline',
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
            <div v-if="store.loading && store.specs.length === 0" class="spec-empty">加载中…</div>
            <div v-else-if="!store.loading && store.specs.length === 0" class="spec-empty">暂无 SPEC</div>
            <button
              v-for="s in store.specs"
              :key="s.id"
              class="spec-row"
              :class="{ active: selected?.id === s.id }"
              @click="selectedId = s.id"
            >
              <div class="spec-row-name">{{ s.app_name }}</div>
              <div class="spec-row-meta">
                <span class="badge badge-brand">v{{ s.latest }}</span>
                <span class="badge badge-emerald">+{{ s.diff_add }}</span>
                <span class="badge badge-amber">~{{ s.diff_mod }}</span>
              </div>
              <div class="spec-row-origin">{{ s.origin }}</div>
            </button>
          </aside>

          <main class="spec-detail" v-if="selected">
            <div class="card card-pad">
              <div class="spec-head">
                <div>
                  <div class="spec-head-app">
                    {{ selected.app_name }}
                    <span
                      class="badge doc-type-chip"
                      :class="docTypeBadgeClass[selected.doc_type || 'spec']"
                    >{{ docTypeLabel[selected.doc_type || 'spec'] }}</span>
                  </div>
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

              <!-- doc_type='spec' 显示 SPEC 6 章节统计；其他类型显示 outline 大纲 -->
              <template v-if="(selected.doc_type || 'spec') === 'spec'">
                <div class="section-head"><div class="section-title">章节</div></div>
                <div class="spec-sections-grid">
                  <div v-for="sec in selected.sections" :key="sec.name" class="spec-section-card">
                    <div class="spec-section-name">{{ sec.name }}</div>
                    <div class="spec-section-count">{{ sec.count }}</div>
                  </div>
                </div>
              </template>
              <template v-else>
                <div class="section-head">
                  <div class="section-title">文档大纲</div>
                  <div class="section-hint">此文档非标准 SPEC，不参与 6 章节解析。</div>
                </div>
                <ul v-if="selected.outline && selected.outline.length > 0" class="outline-list">
                  <li v-for="(t, i) in selected.outline" :key="i" class="outline-item">
                    <span class="outline-idx">{{ i + 1 }}</span>
                    <span class="outline-title">{{ t }}</span>
                  </li>
                </ul>
                <div v-else class="md-excerpt-empty">未抽取到二级标题</div>
              </template>

              <div class="section-head"><div class="section-title">Markdown 摘录</div></div>
              <pre v-if="selected.excerpt" class="md-excerpt"><code>{{ selected.excerpt }}</code></pre>
              <div v-else class="md-excerpt-empty">尚无摘录</div>
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
.section-hint { font-size: 11.5px; color: var(--text-3); margin-top: 2px; }
.doc-type-chip { margin-left: 10px; height: 22px; padding: 0 8px; font-size: 11.5px; vertical-align: middle; }
.outline-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.outline-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; font-size: 13px; color: var(--text); }
.outline-idx { display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 22px; padding: 0 6px; border-radius: 5px; background: var(--surface-3); color: var(--text-3); font-size: 11px; font-family: var(--d-font-mono); }
.outline-title { color: var(--text); }
.md-excerpt { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; overflow-x: auto; color: var(--code-text); font-family: var(--d-font-mono); font-size: 11.5px; line-height: 1.5; }
.md-excerpt-empty { font-size: 12px; color: var(--text-3); padding: 8px 0; }
.spec-empty { font-size: 12.5px; color: var(--text-3); padding: 16px 8px; text-align: center; }
.badge { display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border-radius: 5px; font-size: 11px; font-weight: 500; background: var(--surface-3); color: var(--text-2); border: 1px solid transparent; margin-left: 6px; }
.spec-row-meta .badge { margin-left: 0; }
.badge-brand { background: var(--brand-soft); color: var(--brand-text); }
.badge-emerald { background: var(--emerald-bg); color: var(--emerald); }
.badge-amber { background: var(--amber-bg); color: var(--amber); }
.badge-sky { background: var(--sky-bg); color: var(--sky); }
.badge-outline { background: transparent; border-color: var(--border-strong); }
.mono { font-family: var(--d-font-mono); }
</style>

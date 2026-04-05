<template>
  <WorkbenchShell>
    <div class="apps-main">
      <!-- Filter tabs + view toggle -->
      <div class="filter-bar">
        <div class="filter-tabs">
          <button v-for="tab in tabs" :key="tab.value"
            :class="['filter-tab', { active: activeTab === tab.value }]"
            @click="activeTab = tab.value">
            {{ tab.label }}
            <span class="tab-count" v-if="tabCounts[tab.value]">{{ tabCounts[tab.value] }}</span>
          </button>
        </div>
        <div class="view-toggle">
          <button :class="['toggle-btn', { active: viewMode === 'grid' }]" @click="viewMode = 'grid'" title="卡片视图">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
          </button>
          <button :class="['toggle-btn', { active: viewMode === 'list' }]" @click="viewMode = 'list'" title="列表视图">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
          </button>
        </div>
      </div>

      <!-- Content area -->
      <div class="app-content" :class="viewMode">
      <div v-if="loading" class="empty-state">加载中...</div>
      <div v-else-if="filteredApps.length === 0" class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.3"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        <span>暂无应用</span>
      </div>

      <!-- Grid (card) view -->
      <template v-if="viewMode === 'grid'">
        <div v-for="a in filteredApps" :key="a.id" class="grid-card" @click="router.push({ path: '/chat', query: { app_id: String(a.id) } })">
          <div class="grid-card-top">
            <div class="grid-card-icon" :class="sourceIconClass(a)">{{ sourceIcon(a) }}</div>
            <div class="grid-card-badges">
              <span class="source-badge" :class="a.source">{{ sourceBadgeText(a) }}</span>
              <span class="card-status" :class="statusClass(a)">{{ a.status }}</span>
              <span v-if="a.env_name" class="env-badge">{{ a.env_name }}</span>
            </div>
          </div>
          <h3 class="grid-card-name">{{ a.app_name }}</h3>
          <div class="grid-card-meta">
            <span v-if="a.app_code" class="card-code">{{ a.app_code }}</span>
            <span class="grid-card-date">{{ a.updated_at?.slice(0, 16) }}</span>
          </div>
          <div v-if="a.models || a.forms || a.roles || a.dicts" class="grid-card-stats">
            <span><i class="dot indigo"></i>{{ a.models || 0 }} 模型</span>
            <span><i class="dot emerald"></i>{{ a.forms || 0 }} 表单</span>
            <span><i class="dot amber"></i>{{ a.roles || 0 }} 角色</span>
            <span><i class="dot purple"></i>{{ a.dicts || 0 }} 字典</span>
          </div>
          <div class="grid-card-actions" @click.stop>
            <a v-if="a.apaas_url" :href="a.apaas_url" target="_blank" class="action-btn primary" title="在平台中打开">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </a>
            <button v-if="a.source === 'local' && (a.local_status === 'draft' || a.local_status === 'failed')" class="action-btn primary" @click.stop="router.push({ path: '/chat', query: { deploy_app_id: String(a.id) } })" title="生成到平台">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </button>
            <button class="action-btn danger" @click.stop="confirmDelete(a)" title="删除">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
          </div>
        </div>
      </template>

      <!-- List view -->
      <template v-if="viewMode === 'list'">
        <div v-for="a in filteredApps" :key="a.id" class="list-card" @click="router.push({ path: '/chat', query: { app_id: String(a.id) } })">
          <div class="card-header">
            <div class="card-left">
              <div class="card-icon" :class="sourceIconClass(a)">{{ sourceIcon(a) }}</div>
              <div class="card-info">
                <div class="card-name-row">
                  <h3>{{ a.app_name }}</h3>
                  <span class="source-badge" :class="a.source">{{ sourceBadgeText(a) }}</span>
                  <span class="card-status" :class="statusClass(a)">{{ a.status }}</span>
                  <span v-if="a.env_name" class="env-badge">{{ a.env_name }}</span>
                </div>
                <div class="card-meta">
                  <span>{{ a.updated_at?.slice(0, 16) }}</span>
                  <span v-if="a.app_code" class="card-code">{{ a.app_code }}</span>
                  <span v-if="a.apaas_app_id" class="card-code">ID: {{ a.apaas_app_id }}</span>
                </div>
              </div>
            </div>
            <div class="card-actions" @click.stop>
              <a v-if="a.apaas_url" :href="a.apaas_url" target="_blank" class="action-btn primary" title="在平台中打开">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              </a>
              <button v-if="a.source === 'local' && (a.local_status === 'draft' || a.local_status === 'failed')" class="action-btn primary" @click.stop="router.push({ path: '/chat', query: { deploy_app_id: String(a.id) } })" title="生成到平台">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              </button>
              <button class="action-btn danger" @click.stop="confirmDelete(a)" title="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              </button>
            </div>
          </div>
          <div v-if="a.models || a.forms || a.roles || a.dicts" class="card-stats">
            <span><i class="dot indigo"></i>{{ a.models || 0 }} 模型</span>
            <span><i class="dot emerald"></i>{{ a.forms || 0 }} 表单</span>
            <span><i class="dot amber"></i>{{ a.roles || 0 }} 角色</span>
            <span><i class="dot purple"></i>{{ a.dicts || 0 }} 字典</span>
          </div>
        </div>
      </template>
      </div>
    </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { applicationApi } from '@/api/application'
import type { MergedApplication } from '@/types'
import WorkbenchShell from '@/components/WorkbenchShell.vue'

const router = useRouter()
const apps = ref<MergedApplication[]>([])
const loading = ref(true)
const activeTab = ref('all')
const viewMode = ref<'grid' | 'list'>('grid')

const tabs = [
  { label: '全部', value: 'all' },
  { label: '本地', value: 'local' },
  { label: '平台', value: 'remote' },
  { label: '已同步', value: 'linked' },
]

const tabCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const t of tabs) {
    counts[t.value] = t.value === 'all'
      ? apps.value.length
      : apps.value.filter(a => a.source === t.value).length
  }
  return counts
})

const filteredApps = computed(() => {
  if (activeTab.value === 'all') return apps.value
  return apps.value.filter(a => a.source === activeTab.value)
})

function sourceIcon(a: MergedApplication) {
  if (a.source === 'remote') return '☁️'
  if (a.source === 'linked') return '🔗'
  if (a.local_status === 'completed') return '📊'
  if (a.local_status === 'generating') return '⟳'
  return '📝'
}

function sourceIconClass(a: MergedApplication) {
  if (a.source === 'remote') return 'remote'
  if (a.source === 'linked') return 'linked'
  return a.local_status === 'completed' ? 'success' : 'draft'
}

function sourceBadgeText(a: MergedApplication) {
  if (a.source === 'local') return '本地'
  if (a.source === 'remote') return '平台'
  return '已同步'
}

function statusClass(a: MergedApplication) {
  if (a.source === 'linked') return 'linked'
  if (a.source === 'remote') return 'remote'
  if (a.local_status === 'completed') return 'success'
  if (a.local_status === 'failed') return 'failed'
  return 'draft'
}

async function confirmDelete(a: MergedApplication) {
  try {
    await ElMessageBox.confirm(`确定删除「${a.app_name}」？此操作不可恢复。`, '删除应用', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await applicationApi.delete(Number(a.id))
    apps.value = apps.value.filter(x => x.id !== a.id)
    ElMessage.success('已删除')
  } catch { /* cancelled */ }
}

onMounted(async () => {
  try {
    const list = await applicationApi.list()
    apps.value = Array.isArray(list) ? list : []
  } catch (e) { /* ignore */ }
  loading.value = false
})
</script>

<style scoped>
.apps-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

/* ── Nav ── */
.nav-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  background: var(--t-bg-nav);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--t-border-subtle);
  flex-shrink: 0;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.back-btn {
  background: none;
  border: none;
  color: var(--t-text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  transition: all 0.2s;
}
.back-btn:hover { color: #fff; background: var(--t-border-subtle); }

.logo-box {
  width: 28px;
  height: 28px;
  background: var(--t-brand-gradient);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 700;
  font-size: 12px;
}

.title {
  font-size: 15px;
  font-weight: 600;
  color: var(--t-text-primary);
}

.new-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--t-brand-gradient);
  color: #fff;
  border: none;
  padding: 8px 18px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}
.nav-right-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.new-btn:hover { opacity: 0.9; }

/* ── Filter ── */
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px 0;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.filter-tabs {
  display: flex;
  gap: 4px;
}

.view-toggle {
  display: flex;
  gap: 2px;
  background: var(--t-bg-subtle);
  border-radius: 8px;
  padding: 2px;
}

.toggle-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: none;
  color: var(--t-text-muted);
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.toggle-btn:hover { color: var(--t-text-secondary); }
.toggle-btn.active { background: var(--t-brand-subtle); color: var(--t-brand-light); }

.filter-tab {
  background: none;
  border: none;
  padding: 7px 16px;
  font-size: 13px;
  color: var(--t-text-secondary);
  cursor: pointer;
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s;
}
.filter-tab:hover { background: var(--t-border-subtle); color: var(--t-text-primary); }
.filter-tab.active { background: var(--t-brand-subtle); color: var(--t-brand-light); font-weight: 600; }

.tab-count {
  font-size: 11px;
  background: var(--t-border-subtle);
  color: var(--t-text-secondary);
  padding: 0 7px;
  border-radius: 10px;
  min-width: 20px;
  text-align: center;
}
.filter-tab.active .tab-count { background: var(--t-brand-subtle); color: var(--t-brand-light); }

/* ── Content area ── */
.app-content {
  flex: 1;
  overflow-y: auto;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  padding: 16px 24px 60px;
}

.app-content.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
  align-content: start;
}

.app-content.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.empty-state {
  text-align: center;
  color: var(--t-text-muted);
  padding: 80px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}

/* ── Grid Card ── */
.grid-card {
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-subtle);
  border-radius: 14px;
  padding: 18px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 12px;
  position: relative;
}
.grid-card:hover {
  background: var(--t-bg-input);
  border-color: var(--t-brand-subtle);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  transform: translateY(-2px);
}

.grid-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.grid-card-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}
.grid-card-icon.success { background: var(--t-brand-subtle); }
.grid-card-icon.draft { background: var(--t-border-subtle); }
.grid-card-icon.remote { background: rgba(59, 130, 246, 0.12); }
.grid-card-icon.linked { background: rgba(52, 211, 153, 0.12); }

.grid-card-badges {
  display: flex;
  gap: 4px;
}

.grid-card-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--t-text-primary);
  margin: 0;
  line-height: 1.3;
}

.grid-card-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 11px;
  color: var(--t-text-muted);
}

.grid-card-date { font-size: 11px; }

.grid-card-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--t-bg-subtle);
  font-size: 11px;
  color: var(--t-text-muted);
}

.grid-card-actions {
  display: flex;
  gap: 4px;
  position: absolute;
  bottom: 18px;
  right: 18px;
  opacity: 0;
  transition: opacity 0.2s;
}
.grid-card:hover .grid-card-actions { opacity: 1; }

/* ── List Card ── */
.list-card {
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-subtle);
  border-radius: 14px;
  padding: 18px 20px;
  cursor: pointer;
  transition: all 0.2s;
}
.list-card:hover {
  background: var(--t-bg-input);
  border-color: var(--t-border-subtle);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-left {
  display: flex;
  gap: 14px;
  align-items: center;
  min-width: 0;
}

.card-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.card-icon.success { background: var(--t-brand-subtle); }
.card-icon.draft { background: var(--t-border-subtle); }
.card-icon.remote { background: rgba(59, 130, 246, 0.12); }
.card-icon.linked { background: rgba(52, 211, 153, 0.12); }

.card-info { min-width: 0; }

.card-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.card-name-row h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--t-text-primary);
  margin: 0;
  white-space: nowrap;
}

.source-badge {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
  white-space: nowrap;
}
.source-badge.local { background: var(--t-border-subtle); color: var(--t-text-secondary); }
.source-badge.remote { background: rgba(59, 130, 246, 0.15); color: var(--t-info); }
.source-badge.linked { background: rgba(52, 211, 153, 0.15); color: #34d399; }

.card-status {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 500;
}
.card-status.success { background: rgba(52, 211, 153, 0.15); color: #34d399; }
.card-status.draft { background: var(--t-border-subtle); color: var(--t-text-muted); }
.card-status.linked { background: rgba(52, 211, 153, 0.15); color: #34d399; }
.card-status.remote { background: rgba(59, 130, 246, 0.15); color: var(--t-info); }
.card-status.failed { background: rgba(239, 68, 68, 0.15); color: var(--t-danger); }

.card-meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--t-text-muted);
  align-items: center;
  margin-top: 4px;
  flex-wrap: wrap;
}

.card-code {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 10px;
  color: var(--t-text-muted);
  background: var(--t-border-subtle);
  padding: 1px 6px;
  border-radius: 4px;
}

/* ── Actions ── */
.card-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.action-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-subtle);
  color: var(--t-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  text-decoration: none;
}
.action-btn:hover { background: var(--t-border-subtle); color: #fff; }
.action-btn.primary { border-color: var(--t-brand-subtle); color: var(--t-brand-light); }
.action-btn.primary:hover { background: var(--t-brand-subtle); color: var(--t-brand-light); }
.action-btn.danger { border-color: rgba(239, 68, 68, 0.15); color: rgba(239, 68, 68, 0.5); }
.action-btn.danger:hover { background: rgba(239, 68, 68, 0.1); color: var(--t-danger); }

/* ── Stats ── */
.card-stats {
  display: flex;
  gap: 20px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--t-bg-subtle);
  font-size: 11px;
  color: var(--t-text-muted);
}

.card-stats .dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 5px;
}
.dot.indigo { background: var(--t-brand-light); }
.dot.emerald { background: #34d399; }
.dot.amber { background: var(--t-warning); }
.dot.purple { background: var(--t-brand-light); }

/* ── Env badge ── */
.env-badge {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
  white-space: nowrap;
  background: rgba(56, 189, 248, 0.12);
  color: #38bdf8;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>

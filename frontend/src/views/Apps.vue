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
            <div class="grid-card-icon" :class="sourceIconClass(a)" v-html="appIconSvg(a)"></div>
            <div class="grid-card-badges">
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
          <div v-if="appHistory(a).length" class="conversation-history">
            <div class="conversation-history-title">历史对话</div>
            <button
              v-for="item in appHistory(a)"
              :key="item.id"
              class="conversation-history-item"
              @click.stop="router.push(`/chat/${item.id}?app_id=${a.id}`)"
            >
              <span class="conversation-history-name">{{ historyTitle(item) }}</span>
              <span class="conversation-history-meta">{{ historySummary(item) }} · {{ historyTime(item) }}</span>
            </button>
          </div>
          <div class="grid-card-actions" @click.stop>
            <button v-if="a.apaas_app_id" class="action-btn primary" @click.stop="openInPlatform(a)" title="在平台中打开">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </button>
            <button v-if="a.source === 'local' && (a.local_status === 'draft' || a.local_status === 'failed')" class="action-btn primary" @click.stop="router.push({ path: '/chat', query: { deploy_app_id: String(a.id) } })" title="生成到平台">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </button>
            <button v-if="canDeleteApp(a)" class="action-btn danger" @click.stop="confirmDelete(a)" title="删除">
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
              <div class="card-icon" :class="sourceIconClass(a)" v-html="appIconSvg(a)"></div>
              <div class="card-info">
                <div class="card-name-row">
                  <h3>{{ a.app_name }}</h3>
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
              <button v-if="canDeleteApp(a)" class="action-btn danger" @click.stop="confirmDelete(a)" title="删除">
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
          <div v-if="appHistory(a).length" class="conversation-history list">
            <div class="conversation-history-title">历史对话</div>
            <button
              v-for="item in appHistory(a)"
              :key="item.id"
              class="conversation-history-item"
              @click.stop="router.push(`/chat/${item.id}?app_id=${a.id}`)"
            >
              <span class="conversation-history-name">{{ historyTitle(item) }}</span>
              <span class="conversation-history-meta">{{ historySummary(item) }} · {{ historyTime(item) }}</span>
            </button>
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
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import type { MergedApplication } from '@/types'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { buildPlatformProxyEntryUrl } from '@/utils/platformIframe'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const apps = ref<MergedApplication[]>([])
const appHistoryMap = ref<Record<number, ConversationWithApp[]>>({})
const loading = ref(true)
const activeTab = ref<'all' | 'draft' | 'generating' | 'updating' | 'completed'>('all')
const viewMode = ref<'grid' | 'list'>('grid')

const tabs = [
  { label: '全部', value: 'all' },
  { label: '草稿', value: 'draft' },
  { label: '生成中', value: 'generating' },
  { label: '更新中', value: 'updating' },
  { label: '已生成', value: 'completed' },
]

function matchesTab(a: MergedApplication, tab: typeof activeTab.value) {
  if (tab === 'all') return true
  if (tab === 'completed') return a.local_status === 'completed' || !!a.apaas_app_id
  return a.local_status === tab
}

const tabCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const t of tabs) {
    counts[t.value] = apps.value.filter(a => matchesTab(a, t.value as typeof activeTab.value)).length
  }
  return counts
})

const filteredApps = computed(() => {
  return apps.value.filter(a => matchesTab(a, activeTab.value))
})

const userStore = useUserStore()

function appNumericId(a: MergedApplication) {
  const raw = Number(a.id)
  return Number.isFinite(raw) ? raw : null
}

function openInPlatform(a: MergedApplication) {
  const appId = appNumericId(a)
  if (!appId) return
  const token = userStore.token || localStorage.getItem('token') || ''
  const url = buildPlatformProxyEntryUrl(appId, token)
  window.open(url, '_blank', 'noopener,noreferrer')
}

function appHistory(a: MergedApplication) {
  const id = appNumericId(a)
  if (id == null) return []
  return appHistoryMap.value[id] || []
}

function historyTitle(item: ConversationWithApp) {
  return item.title || item.app_name || '历史对话'
}

function historyTime(item: ConversationWithApp) {
  return (item.updated_at || item.created_at || '').slice(0, 16)
}

function historySummary(item: ConversationWithApp) {
  const count = Number(item.message_count || 0)
  return count > 0 ? `${count} 条消息` : '无消息详情'
}

function buildAppHistoryMap(list: ConversationWithApp[]) {
  const next: Record<number, ConversationWithApp[]> = {}
  for (const item of list) {
    const appId = Number(item.app_id)
    if (!Number.isFinite(appId)) continue
    if (!next[appId]) next[appId] = []
    next[appId].push(item)
  }
  for (const key of Object.keys(next)) {
    const items = next[Number(key)] || []
    next[Number(key)] = items
      .sort((a, b) => new Date(b.updated_at || b.created_at || 0).getTime() - new Date(a.updated_at || a.created_at || 0).getTime())
      .slice(0, 3)
  }
  return next
}

function nameHash(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return h
}

function escapeSvgText(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const ICON_PALETTES = [
  ['#6366f1', '#818cf8'],  // indigo
  ['#0ea5e9', '#38bdf8'],  // sky
  ['#10b981', '#34d399'],  // emerald
  ['#f59e0b', '#fbbf24'],  // amber
  ['#ef4444', '#f87171'],  // red
  ['#8b5cf6', '#a78bfa'],  // violet
  ['#06b6d4', '#22d3ee'],  // cyan
  ['#f97316', '#fb923c'],  // orange
  ['#ec4899', '#f472b6'],  // pink
  ['#14b8a6', '#2dd4bf'],  // teal
]

function appIconInitial(a: MergedApplication): string {
  const appName = String(a.app_name || '').trim()
  const appCode = String(a.app_code || '').trim()
  const source = appName || appCode || 'A'
  const chars = Array.from(source)
  const first = chars.find(char => char.trim()) || 'A'
  return /[a-z]/.test(first) ? first.toUpperCase() : first
}

function appIconBody(a: MergedApplication): string {
  const initial = escapeSvgText(appIconInitial(a))
  return `<text x="24" y="31" text-anchor="middle" font-size="22" font-weight="700"
    font-family="-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif"
    fill="rgba(255,255,255,0.96)">${initial}</text>`
}

function appIconSvg(a: MergedApplication): string {
  const iconSeed = a.app_name || a.app_code || 'app'
  const [c1, c2] = ICON_PALETTES[nameHash(iconSeed) % ICON_PALETTES.length]
  const gradId = `g${nameHash(`${iconSeed}-${a.id}`) % 9999}`

  // 特殊状态覆盖颜色
  const isUpdating = a.local_status === 'updating'
  const isDraft = !a.apaas_app_id && a.local_status !== 'completed'

  const [bg1, bg2] = isUpdating
    ? ['#f59e0b', '#fbbf24']
    : isDraft
      ? ['#94a3b8', '#cbd5e1']
      : [c1, c2]

  return `<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 48 48">
  <defs>
    <linearGradient id="${gradId}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${bg1}"/>
      <stop offset="100%" stop-color="${bg2}"/>
    </linearGradient>
  </defs>
  <rect width="48" height="48" rx="12" fill="url(#${gradId})"/>
  ${appIconBody(a)}
</svg>`
}

function sourceIconClass(a: MergedApplication) {
  if (a.local_status === 'updating') return 'updating'
  if (a.local_status === 'completed' || a.apaas_app_id) return 'success'
  if (a.local_status === 'generating') return 'generating'
  return 'draft'
}

function statusClass(a: MergedApplication) {
  if (a.local_status === 'updating') return 'updating'
  if (a.local_status === 'completed' || a.apaas_app_id) return 'success'
  if (a.local_status === 'generating') return 'generating'
  if (a.local_status === 'failed') return 'failed'
  return 'draft'
}

function canDeleteApp(a: MergedApplication) {
  if (a.source !== 'local') return false
  if (a.apaas_app_id) return false
  return a.local_status === 'draft' || a.local_status === 'failed'
}

function deleteTooltip(a: MergedApplication) {
  if (canDeleteApp(a)) return '删除'
  if (a.source !== 'local') return '平台应用不允许删除'
  if (a.apaas_app_id || a.local_status === 'completed' || a.local_status === 'generating' || a.local_status === 'updating') return '已构建应用不允许删除'
  return '当前状态不允许删除'
}

async function confirmDelete(a: MergedApplication) {
  if (!canDeleteApp(a)) {
    ElMessage.warning(deleteTooltip(a))
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除「${a.app_name}」？此操作不可恢复。`, '删除应用', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await applicationApi.delete(Number(a.id))
    apps.value = apps.value.filter(x => x.id !== a.id)
    ElMessage.success('已删除')
  } catch (error: any) {
    if (error === 'cancel' || error === 'close' || error?.action === 'cancel' || error?.action === 'close') return
    ElMessage.error(error?.response?.data?.detail || error?.message || '删除失败')
  }
}

onMounted(async () => {
  try {
    const [list, conversations] = await Promise.all([
      applicationApi.list({ include_remote: false }),
      conversationApi.listWithApps({ agent_type: 'builder' }).catch(() => []),
    ])
    apps.value = Array.isArray(list) ? list : []
    appHistoryMap.value = buildAppHistoryMap(Array.isArray(conversations) ? conversations : [])
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
  overflow: hidden;
  flex-shrink: 0;
}

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

.conversation-history {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--t-bg-subtle);
}

.conversation-history.list {
  margin-top: 14px;
}

.conversation-history-title {
  font-size: 11px;
  color: var(--t-text-muted);
}

.conversation-history-item {
  width: 100%;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-subtle);
  border-radius: 10px;
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s;
}

.conversation-history-item:hover {
  border-color: var(--t-brand-subtle);
  background: var(--t-bg-input);
}

.conversation-history-name {
  font-size: 12px;
  color: var(--t-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conversation-history-meta {
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
@media (hover: none) { .grid-card-actions { opacity: 1; } }

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
  overflow: hidden;
  flex-shrink: 0;
}

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

.card-status {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 500;
}
.card-status.success { background: rgba(52, 211, 153, 0.15); color: #34d399; }
.card-status.draft { background: var(--t-border-subtle); color: var(--t-text-muted); }
.card-status.generating { background: rgba(96, 165, 250, 0.16); color: #2563eb; }
.card-status.updating { background: rgba(251, 191, 36, 0.16); color: #b7791f; }
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
.action-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  pointer-events: none;
}

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

<template>
  <div class="apps-page">
    <nav class="nav-bar">
      <div class="nav-left">
        <button class="back-btn" @click="router.push('/')"><el-icon><ArrowLeft /></el-icon></button>
        <span class="title">我的应用</span>
      </div>
      <button class="new-btn" @click="router.push('/chat')">+ 新建应用</button>
    </nav>

    <!-- Filter tabs -->
    <div class="filter-bar">
      <button v-for="tab in tabs" :key="tab.value"
        :class="['filter-tab', { active: activeTab === tab.value }]"
        @click="activeTab = tab.value">
        {{ tab.label }}
        <span class="tab-count" v-if="tabCounts[tab.value]">{{ tabCounts[tab.value] }}</span>
      </button>
    </div>

    <div class="app-grid">
      <div v-if="loading" style="text-align:center;color:#9ca3af;padding:48px">加载中...</div>
      <div v-else-if="filteredApps.length === 0" style="text-align:center;color:#9ca3af;padding:48px">暂无应用</div>
      <div v-for="a in filteredApps" :key="a.id" class="app-card">
        <div class="card-top">
          <div class="card-left">
            <div class="card-icon" :class="sourceIconClass(a)">{{ sourceIcon(a) }}</div>
            <div>
              <div class="card-name-row">
                <h3>{{ a.app_name }}</h3>
                <span class="source-badge" :class="a.source">{{ sourceBadgeText(a) }}</span>
              </div>
              <div class="card-meta">
                <span>{{ a.updated_at?.slice(0, 16) }}</span>
                <span v-if="a.app_code" class="card-code">{{ a.app_code }}</span>
                <span v-if="a.apaas_app_id" class="card-code apaas">ID: {{ a.apaas_app_id }}</span>
                <span class="card-status" :class="statusClass(a)">{{ a.status }}</span>
              </div>
            </div>
          </div>
          <div class="card-actions">
            <template v-if="a.source === 'local'">
              <button v-if="a.local_status === 'draft' || a.local_status === 'failed'" class="action-primary" @click="router.push({ path: '/chat', query: { deploy_app_id: String(a.id) } })">生成到平台</button>
              <button v-if="a.local_status === 'completed' && a.apaas_app_id" class="action-primary" @click="router.push({ path: '/chat', query: { deploy_app_id: String(a.id) } })">重新生成</button>
              <button class="action-secondary" @click="router.push({ path: '/chat', query: { app_id: String(a.id) } })">继续完善</button>
              <button class="action-danger" @click="confirmDelete(a)">删除</button>
            </template>
            <template v-else-if="a.source === 'remote'">
              <a v-if="a.apaas_url" :href="a.apaas_url" target="_blank" class="action-primary">在平台中打开</a>
            </template>
            <template v-else>
              <a v-if="a.apaas_url" :href="a.apaas_url" target="_blank" class="action-primary">在平台中打开</a>
              <button class="action-primary" @click="router.push({ path: '/chat', query: { deploy_app_id: String(a.id) } })">重新生成</button>
              <button class="action-secondary" @click="router.push({ path: '/chat', query: { app_id: String(a.id) } })">继续完善</button>
              <button class="action-danger" @click="confirmDelete(a)">删除</button>
            </template>
          </div>
        </div>
        <div v-if="a.models || a.forms || a.roles || a.dicts" class="card-stats">
          <span><i class="dot indigo"></i>{{ a.models || 0 }} 模型</span>
          <span><i class="dot emerald"></i>{{ a.forms || 0 }} 表单</span>
          <span><i class="dot amber"></i>{{ a.roles || 0 }} 角色</span>
          <span><i class="dot purple"></i>{{ a.dicts || 0 }} 字典</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { applicationApi } from '@/api/application'
import type { MergedApplication } from '@/types'

const router = useRouter()
const apps = ref<MergedApplication[]>([])
const loading = ref(true)
const activeTab = ref('all')

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
  return a.local_status === 'completed' ? 'success' : 'generating'
}

function sourceBadgeText(a: MergedApplication) {
  if (a.source === 'local') return '本地'
  if (a.source === 'remote') return '平台应用'
  return '已同步'
}

function statusClass(a: MergedApplication) {
  if (a.source === 'linked') return 'linked'
  if (a.source === 'remote') return 'remote'
  if (a.local_status === 'completed') return 'success'
  if (a.local_status === 'failed') return 'failed'
  return 'generating'
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
.apps-page { height: 100vh; display: flex; flex-direction: column; background: #f9fafb; }
.nav-bar { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; background: #fff; border-bottom: 1px solid #e5e7eb; flex-shrink: 0; }
.nav-left { display: flex; align-items: center; gap: 10px; }
.back-btn { background: none; border: none; color: #9ca3af; cursor: pointer; padding: 4px; }
.title { font-size: 14px; font-weight: 600; color: #1f2937; }
.new-btn { background: #4f46e5; color: #fff; border: none; padding: 6px 16px; border-radius: 8px; font-size: 12px; font-weight: 500; cursor: pointer; }
.new-btn:hover { background: #4338ca; }

.filter-bar { display: flex; gap: 4px; padding: 12px 16px 0; max-width: 900px; margin: 0 auto; width: 100%; }
.filter-tab { background: none; border: none; padding: 6px 14px; font-size: 13px; color: #6b7280; cursor: pointer; border-radius: 8px; display: flex; align-items: center; gap: 6px; transition: all 0.15s; }
.filter-tab:hover { background: #f3f4f6; color: #374151; }
.filter-tab.active { background: #eef2ff; color: #4f46e5; font-weight: 600; }
.tab-count { font-size: 11px; background: #e5e7eb; color: #6b7280; padding: 0 6px; border-radius: 10px; min-width: 18px; text-align: center; }
.filter-tab.active .tab-count { background: #c7d2fe; color: #4338ca; }

.app-grid { flex: 1; overflow-y: auto; max-width: 900px; margin: 0 auto; width: 100%; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.app-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; transition: box-shadow 0.2s; }
.app-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.06); }
.card-top { display: flex; justify-content: space-between; align-items: flex-start; }
.card-left { display: flex; gap: 16px; align-items: center; }
.card-icon { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 18px; }
.card-icon.success { background: #eef2ff; }
.card-icon.generating { background: #fffbeb; }
.card-icon.remote { background: #eff6ff; }
.card-icon.linked { background: #ecfdf5; }
.card-name-row { display: flex; align-items: center; gap: 8px; }
.card-left h3 { font-size: 15px; font-weight: 600; color: #1f2937; margin: 0; }

.source-badge { font-size: 11px; padding: 1px 8px; border-radius: 10px; font-weight: 500; white-space: nowrap; }
.source-badge.local { background: #f3f4f6; color: #6b7280; }
.source-badge.remote { background: #eff6ff; color: #2563eb; }
.source-badge.linked { background: #ecfdf5; color: #059669; }

.card-meta { display: flex; gap: 12px; font-size: 12px; color: #9ca3af; align-items: center; margin-top: 4px; flex-wrap: wrap; }
.card-code { font-family: 'SF Mono', Monaco, Consolas, monospace; font-size: 11px; color: #9ca3af; background: #f3f4f6; padding: 1px 6px; border-radius: 4px; }
.card-code.apaas { color: #6b7280; }
.card-status { padding: 2px 8px; border-radius: 10px; font-size: 11px; }
.card-status.success { background: #ecfdf5; color: #059669; }
.card-status.generating { background: #fffbeb; color: #d97706; }
.card-status.linked { background: #ecfdf5; color: #059669; }
.card-status.remote { background: #eff6ff; color: #2563eb; }
.card-status.failed { background: #fef2f2; color: #dc2626; }

.card-actions { display: flex; gap: 8px; }
.action-primary { font-size: 12px; color: #4f46e5; background: none; border: none; cursor: pointer; padding: 6px 12px; border-radius: 6px; text-decoration: none; }
.action-primary:hover { background: #eef2ff; }
.action-secondary { font-size: 12px; color: #6b7280; background: none; border: none; cursor: pointer; padding: 6px 12px; border-radius: 6px; }
.action-secondary:hover { background: #f3f4f6; }
.action-danger { font-size: 12px; color: #dc2626; background: none; border: none; cursor: pointer; padding: 6px 12px; border-radius: 6px; }
.action-danger:hover { background: #fef2f2; }
.card-stats { display: flex; gap: 24px; margin-top: 16px; font-size: 12px; color: #6b7280; }
.card-stats .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 4px; }
.dot.indigo { background: #818cf8; }
.dot.emerald { background: #34d399; }
.dot.amber { background: #fbbf24; }
.dot.purple { background: #a78bfa; }
</style>

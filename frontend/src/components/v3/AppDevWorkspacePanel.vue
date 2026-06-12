<template>
  <section class="adw" aria-label="自开发工作区">
    <header class="adw-head">
      <div>
        <h1>自开发工作区</h1>
        <p>当前应用关联的自开发页面、组件和后端接口。</p>
      </div>
      <button class="adw-refresh" type="button" :disabled="loading" @click="loadWorkspaces">
        <AppIcon name="refresh" :size="13" />
        <span>刷新</span>
      </button>
    </header>

    <SkeletonCard v-if="loading" :lines="5" />

    <EmptyState
      v-else-if="filteredWorkspaces.length === 0"
      title="暂无自开发工作区"
      desc="通过 AI Builder 生成自开发页面、组件或后端接口后，会在这里归集到当前应用。"
      variant="first"
    >
      <template #icon>
        <AppIcon name="coding" :size="22" />
      </template>
    </EmptyState>

    <div v-else class="adw-table">
      <div class="adw-table-head">
        <span>工作区</span>
        <span>信息</span>
        <span>操作</span>
      </div>

      <div
        v-for="ws in filteredWorkspaces"
        :key="ws.id"
        class="adw-row"
        role="button"
        tabindex="0"
        @click="openWorkspace(ws)"
        @keyup.enter="openWorkspace(ws)"
      >
        <div class="adw-main">
          <span class="adw-avatar" :style="workspaceAccentStyle(ws)">{{ workspaceInitial(ws) }}</span>
          <span class="adw-title">
            <strong>{{ workspaceDisplayName(ws) }}</strong>
            <code>{{ workspaceCodeName(ws) || ws.project_name }}</code>
          </span>
        </div>
        <div class="adw-meta">
          <span class="adw-pill" :data-kind="workspaceGroupKey(ws.project_type)">
            <i aria-hidden="true"></i>{{ workspaceGroupLabel(ws.project_type) }}
          </span>
          <BaseBadge :variant="workspaceStatusVariant(ws.status)" size="sm">
            {{ workspaceStatusLabel(ws.status) }}
          </BaseBadge>
          <span class="adw-updated">{{ relativeTime(ws.updated_at) }}</span>
        </div>
        <div class="adw-actions" @click.stop>
          <button class="adw-action primary" type="button" @click="openWorkspace(ws)">
            <AppIcon name="coding" :size="13" />
            <span>打开</span>
          </button>
          <button class="adw-action" type="button" @click="downloadWorkspace(ws, 'src')">
            <AppIcon name="download" :size="13" />
            <span>源码</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppIcon from '@/components/common/AppIcon.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import BaseBadge from '@/components/BaseBadge.vue'
import { codingApi, type WorkspaceInfo } from '@/api/coding'

const props = defineProps<{
  appId: number
}>()

const router = useRouter()
const loading = ref(true)
const workspaces = ref<WorkspaceInfo[]>([])

const filteredWorkspaces = computed(() =>
  workspaces.value
    .filter(ws => String(ws.project_id || '') === String(props.appId))
    .sort((a, b) => activityTime(b) - activityTime(a)),
)

const groupMap: Record<string, { key: string; label: string }> = {
  'form-component': { key: 'component', label: '组件' },
  'form-component-dual': { key: 'component', label: '双端组件' },
  'menu-page': { key: 'page', label: '页面' },
  'form-page': { key: 'page', label: '页面' },
  'form-list': { key: 'page', label: '页面' },
  plugin: { key: 'plugin', label: '扩展插件' },
  'backend-api': { key: 'backend', label: '后端接口' },
  'backend-feign': { key: 'backend', label: '后端接口' },
  'backend-scheduled': { key: 'backend', label: '后端接口' },
}

const ASSET_ACCENTS = ['#1D4ED8', '#047857', '#B45309', '#0E7490', '#C2410C', '#7C3AED']

async function loadWorkspaces() {
  loading.value = true
  try {
    workspaces.value = await codingApi.listWorkspaces()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载自开发工作区失败')
  } finally {
    loading.value = false
  }
}

function workspaceDisplayName(ws: WorkspaceInfo) {
  return ws.display_name?.trim() || ws.project_name
}

function workspaceCodeName(ws: WorkspaceInfo) {
  const displayName = workspaceDisplayName(ws)
  return displayName !== ws.project_name ? ws.project_name : ''
}

function workspaceGroupLabel(projectType: string) {
  return groupMap[projectType]?.label || '其他'
}

function workspaceGroupKey(projectType: string) {
  return groupMap[projectType]?.key || 'other'
}

function workspaceStatusLabel(status: string) {
  if (status === 'ready') return '已生成'
  if (status === 'building') return '生成中'
  return '本地'
}

function workspaceStatusVariant(status: string): 'success' | 'warn' | 'error' | 'info' | 'neutral' {
  if (status === 'ready') return 'success'
  if (status === 'building') return 'warn'
  return 'neutral'
}

function activityTime(ws: WorkspaceInfo) {
  const updated = new Date(ws.updated_at || '').getTime()
  if (Number.isFinite(updated)) return updated
  return Number(ws.activity_ts || 0)
}

function relativeTime(value?: string | null) {
  if (!value) return '-'
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return String(value).slice(0, 10)
  const diffMs = Date.now() - time
  if (diffMs < 60_000) return '刚刚'
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  if (hours < 48) return '昨天'
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return String(value).slice(0, 10)
}

function nameHash(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return h
}

function workspaceInitial(ws: WorkspaceInfo) {
  const source = workspaceDisplayName(ws) || workspaceCodeName(ws) || ws.project_name || 'C'
  const first = Array.from(source).find(char => char.trim()) || 'C'
  return /[a-z]/.test(first) ? first.toUpperCase() : first
}

function workspaceAccentStyle(ws: WorkspaceInfo) {
  const seed = `${workspaceDisplayName(ws)}|${workspaceCodeName(ws)}|${ws.id}`
  return { background: ASSET_ACCENTS[nameHash(seed) % ASSET_ACCENTS.length] }
}

function openWorkspace(ws: WorkspaceInfo) {
  router.push({ path: '/coding', query: { workspace_id: ws.id } }).catch(() => {})
}

async function downloadWorkspace(ws: WorkspaceInfo, type: 'src' | 'dist') {
  try {
    await codingApi.downloadZip(ws.id, type)
  } catch (e: any) {
    ElMessage.error(e?.message || '下载失败')
  }
}

onMounted(loadWorkspaces)
watch(() => props.appId, loadWorkspaces)
</script>

<style scoped>
.adw {
  flex: 1;
  min-height: 0;
  overflow: auto;
  container-type: inline-size;
  padding: 24px 28px 32px;
  color: var(--text);
  background: var(--bg);
}
.adw-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.adw-head h1 {
  margin: 0;
  font-size: 22px;
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: 0;
}
.adw-head p {
  margin: 6px 0 0;
  color: var(--text-3);
  font-size: 13px;
}
.adw-refresh,
.adw-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.adw-refresh {
  border-color: color-mix(in srgb, var(--brand) 34%, var(--line));
}
.adw-refresh :deep(svg) {
  color: var(--brand);
}
.adw-refresh:hover,
.adw-action:hover {
  border-color: var(--brand);
  color: var(--brand);
}
.adw-refresh:disabled {
  cursor: default;
  opacity: 0.6;
}
.adw-table {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}
.adw-table-head,
.adw-row {
  display: grid;
  grid-template-columns: minmax(240px, 1.5fr) minmax(300px, 1fr) 178px;
  align-items: center;
  column-gap: 16px;
}
.adw-table-head {
  min-height: 42px;
  padding: 0 18px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 12px;
  font-weight: 600;
}
.adw-row {
  min-height: 72px;
  padding: 0 18px;
  border-top: 1px solid var(--line);
  cursor: pointer;
  min-width: 0;
}
.adw-row:hover {
  background: var(--surface-2);
}
.adw-main,
.adw-title,
.adw-actions,
.adw-meta,
.adw-pill {
  display: flex;
  align-items: center;
}
.adw-main {
  gap: 12px;
  min-width: 0;
}
.adw-avatar {
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: white;
  font-weight: 700;
}
.adw-title {
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.adw-title strong,
.adw-title code {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.adw-title strong {
  font-size: 14px;
  color: var(--text);
}
.adw-title code {
  padding: 2px 6px;
  border-radius: 5px;
  background: var(--surface-2);
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 11px;
}
.adw-pill {
  width: fit-content;
  gap: 6px;
  height: 26px;
  padding: 0 9px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}
.adw-pill i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.65;
}
.adw-pill[data-kind="backend"] {
  color: var(--brand);
}
.adw-meta {
  min-width: 0;
  gap: 10px;
}
.adw-updated {
  color: var(--text-3);
  font-size: 12px;
  white-space: nowrap;
}
.adw-actions {
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}
.adw-action span {
  white-space: nowrap;
}
.adw-action.primary {
  border-color: var(--brand);
  background: var(--brand);
  color: var(--text-inverse, #fff);
  font-weight: 600;
}
.adw-action.primary:hover {
  border-color: var(--brand-hover);
  background: var(--brand-hover);
  color: var(--text-inverse, #fff);
}
.adw-action:not(.primary) {
  border-color: color-mix(in srgb, var(--brand) 42%, var(--line));
  background: var(--surface);
  color: var(--text);
  font-weight: 600;
}
.adw-action:not(.primary):hover {
  border-color: var(--brand);
  background: var(--brand-soft);
  color: var(--brand);
}
@media (max-width: 980px) {
  .adw-table-head {
    display: none;
  }
  .adw-row {
    grid-template-columns: 1fr;
    gap: 10px;
    padding: 14px;
  }
  .adw-actions {
    justify-content: flex-start;
  }
}
@container (max-width: 760px) {
  .adw {
    padding: 22px 24px 30px;
  }
  .adw-table-head {
    display: none;
  }
  .adw-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "main actions"
      "meta actions";
    align-items: center;
    gap: 10px 14px;
    min-height: 92px;
    padding: 14px 16px;
  }
  .adw-main {
    grid-area: main;
  }
  .adw-meta {
    grid-area: meta;
    flex-wrap: wrap;
    gap: 8px;
  }
  .adw-actions {
    grid-area: actions;
    flex-direction: column;
    justify-content: center;
    align-items: stretch;
    gap: 6px;
  }
  .adw-action {
    width: 72px;
    height: 28px;
    padding: 0 8px;
  }
}
@container (max-width: 560px) {
  .adw {
    padding: 20px 18px 28px;
  }
  .adw-head {
    align-items: center;
  }
  .adw-head h1 {
    font-size: 20px;
  }
  .adw-head p {
    display: none;
  }
  .adw-row {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "main"
      "meta"
      "actions";
    padding: 14px;
    gap: 12px;
  }
  .adw-avatar {
    width: 36px;
    height: 36px;
  }
  .adw-title code {
    max-width: 100%;
  }
  .adw-actions {
    flex-direction: row;
    justify-content: flex-start;
    width: 100%;
  }
  .adw-action {
    width: auto;
    min-width: 88px;
  }
}
</style>

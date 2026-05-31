<template>
  <BuilderFrame :breadcrumbs="[{ label: 'Vibe Coding' }]">
    <template #actions>
      <button class="online-create-btn" type="button" @click="createWorkspace">
        <el-icon><Plus /></el-icon>
        <span>新建工作区</span>
      </button>
    </template>

    <main class="online-page builder-page">
      <section class="online-header">
        <div class="online-heading">
          <span class="online-kicker">Repository Workspace</span>
          <h1>Vibe Coding</h1>
          <p>管理全代码仓库工作区：导入 Git 仓库、保留开发任务，后续进入 IDE、Agent 和沙箱执行。</p>
        </div>

        <div class="online-summary" aria-label="Vibe Coding 汇总">
          <div>
            <strong>{{ totalCount }}</strong>
            <span>工作区</span>
          </div>
          <div>
            <strong>{{ importedCount }}</strong>
            <span>已导入</span>
          </div>
          <div>
            <strong>{{ failedCount }}</strong>
            <span>需处理</span>
          </div>
        </div>
      </section>

      <section class="online-toolbar" aria-label="工作区筛选">
        <div class="online-tabs" role="tablist" aria-label="工作区状态">
          <button
            v-for="tab in tabs"
            :key="tab.value"
            class="online-tab"
            :class="{ active: activeTab === tab.value }"
            type="button"
            role="tab"
            :aria-selected="activeTab === tab.value"
            @click="activeTab = tab.value"
          >
            <span>{{ tab.label }}</span>
            <span v-if="tab.count" class="online-tab-count">{{ tab.count }}</span>
          </button>
        </div>

        <button class="online-refresh-btn" type="button" :disabled="refreshing" @click="refreshWorkspaces">
          <el-icon :class="{ spin: refreshing }"><Refresh /></el-icon>
          <span>{{ refreshing ? '刷新中' : '刷新' }}</span>
        </button>
        <button
          v-if="hiddenDuplicateWorkspaces.length"
          class="online-clean-btn"
          type="button"
          :disabled="cleaning"
          @click="cleanupHiddenWorkspaces"
        >
          <el-icon><Delete /></el-icon>
          <span>{{ cleaning ? '清理中' : `清理无效 ${hiddenDuplicateWorkspaces.length}` }}</span>
        </button>
      </section>

      <section class="online-content">
        <div v-if="loading" class="online-state">加载中...</div>

        <div v-else-if="filteredWorkspaces.length === 0" class="online-empty">
          <span class="online-empty-icon">
            <el-icon><Connection /></el-icon>
          </span>
          <strong>{{ activeTab === 'all' ? '还没有 Vibe Coding 工作区' : '当前筛选下没有工作区' }}</strong>
          <span>从这里新建一个仓库工作区，之后就能回到列表继续导入、查看状态或进入开发。</span>
          <button class="online-empty-action" type="button" @click="createWorkspace">新建工作区</button>
        </div>

        <template v-else>
          <article
            v-for="workspace in filteredWorkspaces"
            :key="workspace.id"
            class="online-row"
            role="button"
            tabindex="0"
            @click="openWorkspace(workspace)"
            @keyup.enter="openWorkspace(workspace)"
          >
            <div class="online-row-main">
              <span class="online-repo-icon">
                <el-icon><FolderOpened /></el-icon>
              </span>
              <div class="online-row-copy">
                <div class="online-row-title">
                  <h2>{{ workspaceTitle(workspace) }}</h2>
                  <span class="online-status" :class="statusMeta(workspace).tone">
                    {{ statusMeta(workspace).label }}
                  </span>
                </div>
                <div class="online-row-meta">
                  <code>{{ workspace.repo_url || workspace.id }}</code>
                  <span v-if="workspace.branch">分支：{{ workspace.branch }}</span>
                  <span>{{ relativeTime(workspace.updated_at) }}</span>
                </div>
                <p>{{ workspace.task || '未填写开发任务' }}</p>
                <div v-if="workspace.files?.length" class="online-files">
                  <span v-for="file in workspace.files.slice(0, 5)" :key="file">{{ file }}</span>
                  <span v-if="workspace.files.length > 5">+{{ workspace.files.length - 5 }}</span>
                </div>
              </div>
            </div>

            <div class="online-row-side">
              <div class="online-file-count">
                <strong>{{ workspace.file_count || 0 }}</strong>
                <span>文件</span>
              </div>
              <button class="online-open-btn" type="button" @click.stop="openWorkspace(workspace)">
                <span>{{ workspaceActionLabel(workspace) }}</span>
                <el-icon><ArrowRight /></el-icon>
              </button>
              <button
                v-if="canRemoveWorkspace(workspace)"
                class="online-remove-btn"
                type="button"
                :disabled="deletingIds.includes(workspace.id)"
                @click.stop="removeWorkspace(workspace)"
              >
                <el-icon><Delete /></el-icon>
                <span>{{ deletingIds.includes(workspace.id) ? '移除中' : '移除' }}</span>
              </button>
            </div>
          </article>
        </template>
      </section>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowRight,
  Connection,
  Delete,
  FolderOpened,
  Plus,
  Refresh,
} from '@element-plus/icons-vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { onlineCodingApi, type OnlineCodingWorkspace } from '@/api/onlineCoding'

type OnlineTab = 'all' | 'repo_imported' | 'pending' | 'import_failed'

const router = useRouter()
const loading = ref(true)
const refreshing = ref(false)
const cleaning = ref(false)
const deletingIds = ref<string[]>([])
const activeTab = ref<OnlineTab>('all')
const workspaces = ref<OnlineCodingWorkspace[]>([])

const tabDefinitions: Array<{ label: string; value: OnlineTab }> = [
  { label: '全部', value: 'all' },
  { label: '已导入', value: 'repo_imported' },
  { label: '待导入', value: 'pending' },
  { label: '需处理', value: 'import_failed' },
]

const visibleWorkspaces = computed(() => dedupeWorkspaces(workspaces.value).visible)
const hiddenDuplicateWorkspaces = computed(() => dedupeWorkspaces(workspaces.value).hidden)
const totalCount = computed(() => visibleWorkspaces.value.length)
const importedCount = computed(() => visibleWorkspaces.value.filter(isUsableImported).length)
const failedCount = computed(() => visibleWorkspaces.value.filter(needsAttention).length)

const tabs = computed(() =>
  tabDefinitions.map(tab => ({
    ...tab,
    count: tab.value === 'all'
      ? visibleWorkspaces.value.length
      : visibleWorkspaces.value.filter(item => matchesTab(item, tab.value)).length,
  })),
)

const filteredWorkspaces = computed(() => {
  const list = [...visibleWorkspaces.value].sort((a, b) => timeMs(b.updated_at) - timeMs(a.updated_at))
  if (activeTab.value === 'all') return list
  return list.filter(item => matchesTab(item, activeTab.value))
})

function createWorkspace() {
  router.push('/vibe-coding/new')
}

function openWorkspace(workspace: OnlineCodingWorkspace) {
  router.push(`/vibe-coding/workspaces/${workspace.id}`)
}

async function loadWorkspaces() {
  try {
    const list = await onlineCodingApi.listWorkspaces()
    workspaces.value = Array.isArray(list) ? list : []
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || 'Vibe Coding 工作区加载失败')
  } finally {
    loading.value = false
  }
}

async function refreshWorkspaces() {
  refreshing.value = true
  try {
    await loadWorkspaces()
  } finally {
    refreshing.value = false
  }
}

async function removeWorkspace(workspace: OnlineCodingWorkspace) {
  if (deletingIds.value.includes(workspace.id)) return
  try {
    await ElMessageBox.confirm(
      `移除工作区「${workspaceTitle(workspace)}」吗？\n\n会删除本地 Vibe Coding 工作区目录，已导入的仓库副本也会一起删除。`,
      '移除工作区',
      {
        confirmButtonText: '移除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }

  deletingIds.value = [...deletingIds.value, workspace.id]
  try {
    await onlineCodingApi.deleteWorkspace(workspace.id)
    workspaces.value = workspaces.value.filter(item => item.id !== workspace.id)
    ElMessage.success('已移除')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '移除失败')
  } finally {
    deletingIds.value = deletingIds.value.filter(id => id !== workspace.id)
  }
}

async function cleanupHiddenWorkspaces() {
  const targets = hiddenDuplicateWorkspaces.value
  if (!targets.length || cleaning.value) return
  try {
    await ElMessageBox.confirm(
      `清理 ${targets.length} 条重复或无效工作区记录吗？\n\n这些记录已被列表隐藏，通常是导入失败、空仓库或同一仓库的旧尝试。`,
      '清理无效记录',
      {
        confirmButtonText: '清理',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }

  cleaning.value = true
  const ids = targets.map(item => item.id)
  try {
    await Promise.allSettled(ids.map(id => onlineCodingApi.deleteWorkspace(id)))
    workspaces.value = workspaces.value.filter(item => !ids.includes(item.id))
    ElMessage.success('无效记录已清理')
  } finally {
    cleaning.value = false
  }
}

function statusMeta(workspace: OnlineCodingWorkspace) {
  const status = workspace.status
  if (status === 'repo_imported' && !isUsableImported(workspace)) return { label: '空仓库', tone: 'danger' }
  if (status === 'repo_imported') return { label: '已导入', tone: 'success' }
  if (status === 'import_failed') return { label: '需处理', tone: 'danger' }
  if (status === 'repo_importing') return { label: '导入中', tone: 'active' }
  return { label: '待导入', tone: 'draft' }
}

function matchesTab(workspace: OnlineCodingWorkspace, tab: OnlineTab) {
  if (tab === 'all') return true
  if (tab === 'repo_imported') return isUsableImported(workspace)
  if (tab === 'pending') return workspace.status === 'created' || workspace.status === 'repo_importing'
  if (tab === 'import_failed') return needsAttention(workspace)
  return false
}

function dedupeWorkspaces(items: OnlineCodingWorkspace[]) {
  const groups = new Map<string, OnlineCodingWorkspace[]>()
  for (const item of items) {
    const key = workspaceDedupeKey(item)
    groups.set(key, [...(groups.get(key) || []), item])
  }

  const visible: OnlineCodingWorkspace[] = []
  const hidden: OnlineCodingWorkspace[] = []
  for (const group of groups.values()) {
    const ranked = [...group].sort((a, b) => workspaceRank(b) - workspaceRank(a))
    const [keeper, ...rest] = ranked
    if (keeper) visible.push(keeper)
    hidden.push(...rest.filter(isDisposableWorkspace))
    visible.push(...rest.filter(item => !isDisposableWorkspace(item)))
  }
  return { visible, hidden }
}

function workspaceDedupeKey(workspace: OnlineCodingWorkspace) {
  const repo = (workspace.repo_url || '').trim().replace(/\/+$/, '').toLowerCase()
  if (repo) return `repo:${repo}`
  const task = (workspace.task || '').trim().replace(/\s+/g, ' ').toLowerCase()
  return task ? `task:${task}` : `id:${workspace.id}`
}

function workspaceRank(workspace: OnlineCodingWorkspace) {
  const statusWeight = isUsableImported(workspace)
    ? 400
    : workspace.status === 'repo_importing'
      ? 300
      : workspace.status === 'created'
        ? 200
        : 100
  return (
    statusWeight * 1_000_000_000_000 +
    Math.min(workspace.file_count || 0, 999_999) * 1_000_000 +
    timeMs(workspace.updated_at)
  )
}

function isDisposableWorkspace(workspace: OnlineCodingWorkspace) {
  return !isUsableImported(workspace)
}

function canRemoveWorkspace(workspace: OnlineCodingWorkspace) {
  return !isUsableImported(workspace)
}

function isUsableImported(workspace: OnlineCodingWorkspace) {
  return workspace.status === 'repo_imported' && (workspace.file_count || workspace.files?.length || 0) > 0
}

function needsAttention(workspace: OnlineCodingWorkspace) {
  return workspace.status === 'import_failed' || (workspace.status === 'repo_imported' && !isUsableImported(workspace))
}

function workspaceTitle(workspace: OnlineCodingWorkspace) {
  const fromRepo = repoName(workspace.repo_url)
  return fromRepo || workspace.id
}

function workspaceActionLabel(workspace: OnlineCodingWorkspace) {
  if (isUsableImported(workspace)) return '进入 AI 工作台'
  if (workspace.status === 'import_failed') return '处理'
  if (workspace.status === 'repo_imported') return '重新处理'
  return '继续导入'
}

function repoName(repoUrl?: string | null) {
  if (!repoUrl) return ''
  const cleaned = repoUrl.trim().replace(/\/+$/, '')
  const name = cleaned.split('/').filter(Boolean).pop() || ''
  return name.replace(/\.git$/i, '')
}

function normalizeTimestamp(value?: string | null) {
  if (!value) return ''
  const normalized = String(value).trim()
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(normalized)
  const isDateTime = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(normalized)
  return isDateTime && !hasTimezone ? `${normalized.replace(' ', 'T')}Z` : normalized
}

function timeMs(value?: string | null) {
  const normalized = normalizeTimestamp(value)
  if (!normalized) return 0
  const time = new Date(normalized).getTime()
  return Number.isFinite(time) ? time : 0
}

function relativeTime(value?: string | null) {
  const time = timeMs(value)
  if (!time) return '-'
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

onMounted(loadWorkspaces)
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   v2 indigo-violet hex (#5d6df2, #4f5fe0, rgba(99,102,241,*)) → v3 brand-blue
   tokens. 4-tier weights, 5-tier sizes, r-/sh-/ease, a11y rings. */

.online-create-btn,
.online-empty-action,
.online-open-btn,
.online-clean-btn,
.online-remove-btn,
.online-refresh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  font-weight: var(--fw-semibold);
  cursor: pointer;
  transition: background 0.14s var(--ease), border-color 0.14s var(--ease), color 0.14s var(--ease), transform 0.14s var(--ease);
}

.online-create-btn,
.online-empty-action,
.online-open-btn,
.online-clean-btn,
.online-remove-btn,
.online-refresh-btn {
  font-family: inherit;
}

.online-create-btn:focus-visible,
.online-empty-action:focus-visible,
.online-open-btn:focus-visible,
.online-clean-btn:focus-visible,
.online-remove-btn:focus-visible,
.online-refresh-btn:focus-visible {
  outline: 2px solid var(--line-focus);
  outline-offset: 2px;
}

.online-create-btn {
  height: 30px;
  gap: var(--s-2);
  border-color: var(--brand);
  border-radius: var(--r-2);
  background: var(--brand);
  color: #fff;
  padding: 0 var(--s-3);
  font-size: var(--t-mono);
}

.online-create-btn:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.online-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 28px 44px;
  color: var(--text);
  background: var(--bg);
}

.online-header,
.online-toolbar,
.online-content {
  width: min(100%, 1180px);
  margin: 0 auto;
}

.online-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-5);
}

.online-heading {
  min-width: 0;
}

.online-kicker {
  display: block;
  margin-bottom: var(--s-2);
  color: var(--brand);
  font-family: var(--font-mono);
  font-size: var(--t-micro);
  font-weight: var(--fw-bold);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.online-heading h1 {
  margin: 0;
  color: var(--text);
  font-size: var(--t-h1);
  font-weight: var(--fw-bold);
  line-height: 1.15;
  letter-spacing: 0;
}

.online-heading p {
  margin: var(--s-2) 0 0;
  max-width: 680px;
  color: var(--text-2);
  font-size: var(--t-body);
  line-height: 1.65;
}

.online-summary {
  display: grid;
  grid-template-columns: repeat(3, 76px);
  gap: var(--s-2);
  flex-shrink: 0;
}

.online-summary > div {
  min-height: 58px;
  padding: var(--s-3);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
  background: var(--surface);
}

.online-summary strong {
  display: block;
  color: var(--text);
  font-size: 20px;
  font-weight: var(--fw-semibold);
  line-height: 1;
}

.online-summary span {
  display: block;
  margin-top: var(--s-2);
  color: var(--text-2);
  font-size: var(--t-mono);
}

.online-toolbar {
  margin-top: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-4);
}

.online-tabs {
  display: flex;
  gap: var(--s-1);
  flex-wrap: wrap;
}

.online-tab,
.online-refresh-btn {
  height: 34px;
  border: 1px solid var(--line);
  border-radius: var(--r-3);
  background: var(--surface);
  color: var(--text-2);
  font-size: var(--t-mono);
  font-weight: var(--fw-semibold);
  cursor: pointer;
}

.online-tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 13px;
}

.online-tab:hover,
.online-refresh-btn:hover {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  color: var(--brand);
}

.online-tab.active {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  color: var(--brand-text);
}

.online-tab-count {
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: var(--r-full);
  background: var(--brand-soft-2);
  color: inherit;
  line-height: 18px;
  text-align: center;
  font-size: var(--t-micro);
}

.online-refresh-btn {
  gap: var(--s-2);
  padding: 0 var(--s-3);
}

.online-clean-btn {
  height: 34px;
  gap: var(--s-2);
  padding: 0 var(--s-3);
  border-color: var(--err);
  border-radius: var(--r-3);
  background: var(--err-soft);
  color: var(--err);
  font-size: var(--t-mono);
}

.online-clean-btn:hover {
  border-color: var(--err);
  background: var(--err-soft);
  color: var(--err);
}

.online-refresh-btn:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.online-content {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.online-state,
.online-empty,
.online-row {
  border: 1px solid var(--line);
  border-radius: var(--r-4);
  background: var(--surface);
}

.online-state,
.online-empty {
  min-height: 260px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 36px;
  color: var(--text-2);
}

.online-empty {
  gap: var(--s-3);
}

.online-empty strong {
  color: var(--text);
  font-size: var(--t-body);
  font-weight: var(--fw-semibold);
}

.online-empty span:not(.online-empty-icon) {
  max-width: 440px;
  font-size: var(--t-body);
  line-height: 1.65;
}

.online-empty-icon {
  width: 42px;
  height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--r-5);
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 22px;
}

.online-empty-action {
  height: 34px;
  margin-top: var(--s-2);
  padding: 0 14px;
  border-color: var(--brand);
  border-radius: var(--r-3);
  background: var(--brand);
  color: #fff;
  font-size: var(--t-mono);
}

.online-empty-action:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.online-row {
  padding: 13px 14px;
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 14px;
  cursor: pointer;
  transition: border-color 0.18s var(--ease), box-shadow 0.18s var(--ease), transform 0.18s var(--ease);
}

.online-row:hover {
  transform: translateY(-1px);
  border-color: var(--brand-ring);
  box-shadow: var(--sh-3);
}

.online-row:focus-visible {
  outline: 2px solid var(--line-focus);
  outline-offset: 2px;
}

.online-row-main {
  min-width: 0;
  display: flex;
  gap: 14px;
  flex: 1;
}

.online-repo-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--r-3);
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 18px;
}

.online-row-copy {
  min-width: 0;
  flex: 1;
}

.online-row-title,
.online-row-meta,
.online-files {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.online-row-title {
  gap: var(--s-2);
}

.online-row-title h2 {
  margin: 0;
  min-width: 0;
  color: var(--text);
  font-size: var(--t-body);
  font-weight: var(--fw-semibold);
  line-height: 1.35;
  word-break: break-word;
}

.online-status {
  height: 22px;
  padding: 0 var(--s-2);
  border-radius: var(--r-full);
  font-size: var(--t-micro);
  font-weight: var(--fw-bold);
  line-height: 22px;
}

.online-status.success {
  background: var(--ok-soft);
  color: var(--ok);
}

.online-status.danger {
  background: var(--err-soft);
  color: var(--err);
}

.online-status.active {
  background: var(--info-soft);
  color: var(--info);
}

.online-status.draft {
  background: var(--surface-3);
  color: var(--text-3);
}

.online-row-meta {
  margin-top: 7px;
  gap: var(--s-2);
  color: var(--text-3);
  font-size: var(--t-mono);
}

.online-row-meta code {
  max-width: min(580px, 100%);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-2);
  font-family: var(--font-mono);
}

.online-row-copy p {
  margin: 7px 0 0;
  color: var(--text-2);
  font-size: var(--t-body);
  line-height: 1.65;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.online-files {
  margin-top: var(--s-2);
  gap: var(--s-2);
}

.online-files span {
  max-width: 180px;
  height: 24px;
  padding: 0 var(--s-2);
  border: 1px solid var(--line);
  border-radius: var(--r-3);
  background: var(--surface-2);
  color: var(--text-3);
  font-size: var(--t-micro);
  line-height: 23px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.online-row-side {
  width: 132px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s-2);
}

.online-file-count {
  text-align: right;
}

.online-file-count strong {
  display: block;
  color: var(--text);
  font-size: 18px;
  font-weight: var(--fw-semibold);
  line-height: 1;
}

.online-file-count span {
  display: block;
  margin-top: 5px;
  color: var(--text-3);
  font-size: var(--t-micro);
}

.online-open-btn {
  height: 32px;
  gap: var(--s-1);
  padding: 0 11px;
  border-color: var(--brand-ring);
  border-radius: var(--r-3);
  background: var(--brand-soft);
  color: var(--brand);
  font-size: var(--t-mono);
}

.online-open-btn:hover {
  background: var(--brand-soft-2);
  border-color: var(--brand);
}

.online-remove-btn {
  height: 30px;
  gap: var(--s-1);
  padding: 0 10px;
  border-color: var(--line);
  border-radius: var(--r-3);
  background: transparent;
  color: var(--text-3);
  font-size: var(--t-mono);
}

.online-remove-btn:hover {
  border-color: var(--err);
  background: var(--err-soft);
  color: var(--err);
}

.online-open-btn:hover,
.online-empty-action:hover,
.online-create-btn:hover {
  transform: translateY(-1px);
}

.spin {
  animation: online-spin 0.9s linear infinite;
}

@keyframes online-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 860px) {
  .online-page {
    padding: 22px 18px 40px;
  }

  .online-header,
  .online-toolbar,
  .online-row {
    align-items: stretch;
    flex-direction: column;
  }

  .online-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .online-row-side {
    width: 100%;
    flex-direction: row;
    align-items: center;
  }

  .online-file-count {
    text-align: left;
  }
}

/* v3 dark theme — all explicit colors now route through v3 dark tokens.
   design-v3-tokens.css already remaps --surface / --text / --brand etc when
   html[data-theme="dark"] is set, so most rules can simply use the same var. */

:global(html[data-theme="dark"] .online-page) {
  background: var(--bg) !important;
}

:global(html[data-theme="dark"] .online-create-btn),
:global(html[data-theme="dark"] .online-empty-action) {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}

:global(html[data-theme="dark"] .online-summary > div),
:global(html[data-theme="dark"] .online-tab),
:global(html[data-theme="dark"] .online-refresh-btn),
:global(html[data-theme="dark"] .online-clean-btn),
:global(html[data-theme="dark"] .online-remove-btn),
:global(html[data-theme="dark"] .online-state),
:global(html[data-theme="dark"] .online-empty),
:global(html[data-theme="dark"] .online-row),
:global(html[data-theme="dark"] .online-files span) {
  background: var(--surface) !important;
  border-color: var(--line) !important;
  box-shadow: var(--sh-1) !important;
}

:global(html[data-theme="dark"] .online-summary > div),
:global(html[data-theme="dark"] .online-row) {
  background: var(--surface) !important;
}

:global(html[data-theme="dark"] .online-row:hover) {
  background: var(--surface-2) !important;
  border-color: var(--brand-ring) !important;
  box-shadow: var(--sh-3) !important;
}

:global(html[data-theme="dark"] .online-heading h1),
:global(html[data-theme="dark"] .online-summary strong),
:global(html[data-theme="dark"] .online-empty strong),
:global(html[data-theme="dark"] .online-row-title h2),
:global(html[data-theme="dark"] .online-file-count strong) {
  color: var(--text);
}

:global(html[data-theme="dark"] .online-heading p),
:global(html[data-theme="dark"] .online-summary span),
:global(html[data-theme="dark"] .online-empty span:not(.online-empty-icon)),
:global(html[data-theme="dark"] .online-row-copy p),
:global(html[data-theme="dark"] .online-row-meta),
:global(html[data-theme="dark"] .online-file-count span) {
  color: var(--text-3);
}

:global(html[data-theme="dark"] .online-row-meta code) {
  color: var(--text-2);
}

:global(html[data-theme="dark"] .online-kicker),
:global(html[data-theme="dark"] .online-empty-icon),
:global(html[data-theme="dark"] .online-repo-icon) {
  color: var(--brand);
}

:global(html[data-theme="dark"] .online-empty-icon),
:global(html[data-theme="dark"] .online-repo-icon),
:global(html[data-theme="dark"] .online-tab.active),
:global(html[data-theme="dark"] .online-open-btn) {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  color: var(--brand-text);
}

:global(html[data-theme="dark"] .online-tab:not(.active)),
:global(html[data-theme="dark"] .online-refresh-btn),
:global(html[data-theme="dark"] .online-remove-btn) {
  color: var(--text-2) !important;
}

:global(html[data-theme="dark"] .online-clean-btn),
:global(html[data-theme="dark"] .online-remove-btn:hover) {
  background: var(--err-soft) !important;
  border-color: var(--err) !important;
  color: var(--err) !important;
}

:global(html[data-theme="dark"] .online-tab.active) {
  background: var(--brand-soft) !important;
  border-color: var(--brand-ring) !important;
  color: var(--brand-text) !important;
}

:global(html[data-theme="dark"] .online-status.success) {
  background: var(--ok-soft) !important;
  color: var(--ok) !important;
}

:global(html[data-theme="dark"] .online-status.danger) {
  background: var(--err-soft) !important;
  color: var(--err) !important;
}

:global(html[data-theme="dark"] .online-status.draft),
:global(html[data-theme="dark"] .online-status.active) {
  background: var(--surface-3) !important;
  color: var(--text-2) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-summary > div),
:global(html[data-theme="dark"] .builder-view .online-page .online-row),
:global(html[data-theme="dark"] .builder-view .online-page .online-state),
:global(html[data-theme="dark"] .builder-view .online-page .online-empty) {
  background: var(--surface) !important;
  border-color: var(--line-strong) !important;
  color: var(--text) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-tab),
:global(html[data-theme="dark"] .builder-view .online-page .online-refresh-btn),
:global(html[data-theme="dark"] .builder-view .online-page .online-remove-btn) {
  background: var(--surface) !important;
  border-color: var(--line-strong) !important;
  color: var(--text-2) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-clean-btn) {
  background: var(--err-soft) !important;
  border-color: var(--err) !important;
  color: var(--err) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-row:hover) {
  background: var(--surface-2) !important;
  border-color: var(--brand-ring) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-heading h1),
:global(html[data-theme="dark"] .builder-view .online-page .online-row-title h2),
:global(html[data-theme="dark"] .builder-view .online-page .online-summary strong),
:global(html[data-theme="dark"] .builder-view .online-page .online-file-count strong) {
  color: var(--text) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-heading p),
:global(html[data-theme="dark"] .builder-view .online-page .online-row-copy p),
:global(html[data-theme="dark"] .builder-view .online-page .online-row-meta),
:global(html[data-theme="dark"] .builder-view .online-page .online-summary span),
:global(html[data-theme="dark"] .builder-view .online-page .online-file-count span) {
  color: var(--text-3) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-row-meta code) {
  color: var(--text-2) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-files span) {
  background: var(--surface-2) !important;
  border-color: var(--line) !important;
  color: var(--text-2) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-repo-icon),
:global(html[data-theme="dark"] .builder-view .online-page .online-empty-icon) {
  background: var(--brand-soft) !important;
  color: var(--brand) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-open-btn) {
  background: var(--brand-soft) !important;
  border-color: var(--brand-ring) !important;
  color: var(--brand-text) !important;
}

:global(html[data-theme="dark"] .builder-view .online-page .online-create-btn) {
  background: var(--brand) !important;
  border-color: var(--brand) !important;
  color: #fff !important;
}
</style>

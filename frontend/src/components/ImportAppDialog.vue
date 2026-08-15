<template>
  <el-dialog
    v-model="visible"
    title="导入平台应用"
    width="760px"
    class="import-app-dialog"
    destroy-on-close
    @close="$emit('update:modelValue', false)"
  >
    <div class="import-body">
      <div class="import-hero">
        <div>
          <div class="import-hero-desc">
            同步已上线应用；已导入的应用再次导入时，会追加新的设计文档版本。
          </div>
        </div>
      </div>

      <div class="import-panel">
        <div class="app-list-section">
          <div class="search-row">
            <el-input
              v-model="searchText"
              placeholder="搜索应用名称或编码..."
              :prefix-icon="Search"
              clearable
            />
          </div>

          <div class="import-stats" aria-label="平台应用统计">
            <div class="import-stats-item">
              <span class="stats-value">{{ remoteApps.length }}</span>
              <span class="stats-label">全部应用</span>
            </div>
            <div class="import-stats-item">
              <span class="stats-value">{{ importedCount }}</span>
              <span class="stats-label">已导入</span>
            </div>
            <div class="import-stats-item">
              <span class="stats-value">{{ onlineCount }}</span>
              <span class="stats-label">可导入</span>
            </div>
          </div>

          <div v-if="loading" class="loading-tip">
            <el-icon class="is-loading"><Loading /></el-icon>
            正在加载平台应用...
          </div>

          <div v-else-if="filteredApps.length === 0" class="empty-tip">
            {{ emptyText }}
          </div>

          <div v-else class="app-list">
            <div class="app-list-header">
              <span class="header-app">应用</span>
              <span>状态</span>
              <span>导入方式</span>
            </div>
            <div
              v-for="app in filteredApps"
              :key="app.apaas_app_id"
              class="app-item"
              :class="{
                selected: selectedAppId === app.apaas_app_id,
                imported: app.already_imported,
              }"
              role="button"
              tabindex="0"
              @click="selectedAppId = app.apaas_app_id"
              @keydown.enter.prevent="selectedAppId = app.apaas_app_id"
              @keydown.space.prevent="selectedAppId = app.apaas_app_id"
            >
              <div class="app-item-select">
                <div class="radio-dot" :class="{ active: selectedAppId === app.apaas_app_id }" />
              </div>
              <div class="app-item-main">
                <div class="app-item-name">{{ app.app_name }}</div>
                <div class="app-item-meta">
                  <span v-if="app.app_code" class="app-item-code">{{ app.app_code }}</span>
                  <span v-if="selectedAppId === app.apaas_app_id" class="selected-chip">已选择</span>
                </div>
                <div v-if="app.description" class="app-item-desc">{{ app.description }}</div>
              </div>
              <div class="app-item-status">
                <span class="app-item-tag" :class="app.already_imported ? 'tag-imported' : 'tag-online'">
                  {{ app.already_imported ? '已导入' : '已上线' }}
                </span>
              </div>
              <div class="app-item-action">
                <span>{{ app.already_imported ? '追加版本' : '新建本地应用' }}</span>
              </div>
            </div>
          </div>

          <div v-if="selectedApp" class="selection-tip">
            <span class="selection-tip-label">当前选择</span>
            <span class="selection-tip-name">{{ selectedApp.app_name }}</span>
            <span class="selection-tip-action">
              {{ selectedApp.already_imported ? '重新导入后会新增一个版本记录' : '将导入为新的本地应用' }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <div class="footer-hint">
          {{ selectedIsImported ? '重新导入不会覆盖历史记录，只会追加新版本。' : '导入后会自动生成设计文档与版本记录。' }}
        </div>
        <div class="footer-actions">
          <el-button @click="visible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="importing"
            :disabled="!selectedAppId"
            @click="doImport"
          >
            {{ selectedIsImported ? '重新导入' : '导入选中应用' }}
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Search, Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { RemoteApp } from '@/api/platformEnv'
import { controlPlaneApaasApi } from '@/api/controlPlaneApaas'
import { standaloneApaasApi } from '@/api/standaloneApaas'
import { getDesktopState, isDesktop } from '@/utils/desktop'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [val: boolean]
  imported: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const remoteApps = ref<RemoteApp[]>([])
const selectedAppId = ref<string>('')
const searchText = ref('')
const loading = ref(false)
const importing = ref(false)
type ImportSource = 'control-plane' | 'standalone-apaas'
// Discovery is authoritative. Account/tenant profile fields cannot tell which
// backend owns the current deployment and previously routed standalone imports
// to the legacy Python Builder API.
const importSource = ref<ImportSource>('control-plane')

const selectedIsImported = computed(() =>
  remoteApps.value.find((a) => a.apaas_app_id === selectedAppId.value)?.already_imported ?? false
)

const selectedApp = computed(() =>
  remoteApps.value.find((a) => a.apaas_app_id === selectedAppId.value) ?? null
)

const importedCount = computed(() =>
  remoteApps.value.filter((a) => a.already_imported).length
)

const onlineCount = computed(() =>
  remoteApps.value.filter((a) => !a.already_imported).length
)

const filteredApps = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  if (!q) return remoteApps.value
  return remoteApps.value.filter(
    (a) =>
      (a.app_name || '').toLowerCase().includes(q) ||
      (a.app_code || '').toLowerCase().includes(q)
  )
})

const emptyText = computed(() => {
  if (remoteApps.value.length === 0) return '暂无已上线应用'
  return '无匹配结果'
})

async function resolveImportSource(): Promise<ImportSource> {
  // Web standalone builds do not have the Tauri discovery bridge. Their
  // product base path is authoritative and must keep application import on
  // the standalone Builder AI backend instead of Control Plane.
  const pathname = typeof window !== 'undefined' ? window.location.pathname.toLowerCase() : ''
  const standaloneWebPath = pathname === '/builder-standalone'
    || pathname.startsWith('/builder-standalone/')
  if (!isDesktop && standaloneWebPath) return 'standalone-apaas'
  if (!isDesktop) return 'control-plane'
  try {
    const state = await getDesktopState()
    const discovery = state.config?.discovery
    const deploymentId = String(discovery?.deployment_id || '').toLowerCase()
    const platformType = String(discovery?.platform?.type || '').toLowerCase()
    const provider = String(discovery?.auth?.provider || state.config?.login?.mode || '').toLowerCase()
    return deploymentId === 'builder-standalone'
      || platformType === 'apaas_builder'
      || provider === 'apaas'
      ? 'standalone-apaas'
      : 'control-plane'
  } catch {
    return 'control-plane'
  }
}

watch(
  () => props.modelValue,
  async (v) => {
    if (v) {
      remoteApps.value = []
      selectedAppId.value = ''
      searchText.value = ''
      importSource.value = await resolveImportSource()
      try {
        await loadRemoteApps()
      } catch (e: any) {
        ElMessage.error('加载平台应用失败')
      }
    }
  }
)

async function loadRemoteApps() {
  selectedAppId.value = ''
  searchText.value = ''
  loading.value = true
  try {
    if (importSource.value === 'control-plane') {
      const page = await controlPlaneApaasApi.listApplications()
      remoteApps.value = (page.items || []).map((app) => ({
        apaas_app_id: app.appId,
        app_name: app.appName || app.appCode || '未命名应用',
        app_code: app.appCode || '',
        description: app.description || '',
        status: app.status || '已上线',
        already_imported: Boolean(app.alreadyImported),
      }))
    } else {
      const page = await standaloneApaasApi.listApplications()
      const items = Array.isArray(page) ? page : (page.items || [])
      remoteApps.value = items.map((app) => ({
        apaas_app_id: String(app.appId ?? ''),
        app_name: app.appName || app.appCode || '未命名应用',
        app_code: app.appCode || '',
        description: app.description || '',
        status: app.status || '已上线',
        already_imported: Boolean(app.already_imported ?? app.alreadyImported),
      }))
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '加载平台应用失败')
    remoteApps.value = []
  } finally {
    loading.value = false
  }
}

async function doImport() {
  if (!selectedAppId.value) return
  importing.value = true
  try {
    if (importSource.value === 'control-plane') {
      await controlPlaneApaasApi.importApplication(selectedAppId.value)
    } else {
      await standaloneApaasApi.importApplication(selectedAppId.value)
    }
    ElMessage.success('应用导入成功')
    visible.value = false
    emit('imported')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '导入失败'
    ElMessage.error(msg)
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
.import-body {
  --import-primary: var(--brand);
  --import-primary-soft: var(--brand-soft);
  --import-border: var(--line);
  --import-border-strong: var(--brand-ring, var(--brand));
  --import-text: var(--text);
  --import-text-soft: var(--text-3);
  --import-bg: var(--surface-2);
  min-height: 220px;
  color: var(--text);
}

.import-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 2px 2px 18px;
}

.import-hero-desc {
  max-width: 440px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--import-text-soft);
}

.import-panel {
  padding: 14px;
  border: 1px solid var(--import-border);
  border-radius: 8px;
  background: var(--surface);
}

.app-list-section {
  margin-top: 0;
}

.search-row {
  margin-bottom: 10px;
}

.import-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.import-stats-item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-height: 44px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--surface);
  border: 1px solid var(--import-border);
}

.stats-value {
  font-size: 18px;
  line-height: 1;
  font-weight: 800;
  color: var(--text);
}

.stats-label {
  font-size: 12px;
  color: var(--import-text-soft);
}

.loading-tip,
.empty-tip {
  padding: 44px 0;
  text-align: center;
  color: var(--import-text-soft);
  font-size: 13px;
}

.loading-tip .el-icon {
  margin-right: 6px;
  vertical-align: middle;
}

.app-list {
  max-height: 340px;
  overflow-y: auto;
  border: 1px solid var(--import-border);
  border-radius: 8px;
  background: var(--surface);
}

.app-list-header {
  position: sticky;
  top: 0;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 96px 132px;
  gap: 16px;
  align-items: center;
  padding: 9px 16px 9px 56px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 12px;
  font-weight: 700;
}

.header-app {
  min-width: 0;
}

.app-item {
  position: relative;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 96px 132px;
  gap: 16px;
  align-items: center;
  min-height: 78px;
  padding: 13px 16px;
  cursor: pointer;
  outline: none;
  transition: background 0.18s, box-shadow 0.18s;
  border-bottom: 1px solid var(--line);
}

.app-item:last-child {
  border-bottom: none;
}

.app-item:hover {
  background: color-mix(in srgb, var(--brand-soft) 36%, var(--surface));
}

.app-item:focus-visible {
  box-shadow: inset 0 0 0 2px var(--brand-ring, var(--brand));
}

.app-item.selected {
  background: var(--brand-soft);
  box-shadow: inset 3px 0 0 var(--brand), inset 0 0 0 1px var(--brand-ring, var(--brand));
}

.app-item.imported {
  background-image: none;
}

.app-item-select {
  display: flex;
  align-items: center;
  justify-content: center;
}

.app-item-main {
  min-width: 0;
}

.radio-dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid var(--line-strong);
  transition: all 0.2s;
}

.radio-dot.active {
  border-color: var(--import-primary);
  background: var(--import-primary);
  box-shadow: inset 0 0 0 3px var(--surface);
}

.app-item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}

.app-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 22px;
  margin-top: 3px;
}

.app-item-code {
  display: inline-flex;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-3);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}

.selected-chip {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--brand);
  color: var(--surface);
  font-size: 11px;
  font-weight: 700;
}

.app-item-desc {
  display: -webkit-box;
  margin-top: 2px;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  font-size: 12px;
  line-height: 1.5;
  color: var(--import-text-soft);
}

.app-item-status {
  display: flex;
  align-items: center;
  justify-content: flex-start;
}

.app-item-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 58px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.tag-online {
  background: var(--ok-soft);
  color: var(--ok);
}

.tag-imported {
  background: var(--surface-3);
  color: var(--text-3);
}

.app-item-action {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  color: var(--text-4);
  text-align: right;
}

.app-item.selected .app-item-action {
  color: var(--brand);
  font-weight: var(--fw-semibold, 600);
}

.selection-tip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 14px;
  background: var(--brand-soft);
  border: 1px solid var(--brand-ring, var(--line));
}

.selection-tip-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--import-primary);
}

.selection-tip-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
}

.selection-tip-action {
  font-size: 12px;
  color: var(--import-text-soft);
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.footer-hint {
  font-size: 12px;
  line-height: 1.5;
  color: var(--import-text-soft);
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

@media (max-width: 768px) {
  .import-hero,
  .dialog-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .import-stats {
    grid-template-columns: 1fr;
  }

  .app-list-header {
    display: none;
  }

  .app-item {
    grid-template-columns: 28px minmax(0, 1fr);
    row-gap: 8px;
  }

  .app-item-status,
  .app-item-action {
    grid-column: 2;
  }

  .app-item-action {
    justify-content: flex-start;
    text-align: left;
  }

  .footer-actions {
    justify-content: flex-end;
  }
}
</style>

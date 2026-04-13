<template>
  <el-dialog
    v-model="visible"
    title="从平台导入应用"
    width="640px"
    class="import-app-dialog"
    destroy-on-close
    @close="$emit('update:modelValue', false)"
  >
    <div class="import-body">
      <div class="import-hero">
        <div>
          <div class="import-hero-title">选择平台应用</div>
          <div class="import-hero-desc">
            已导入的应用也可以重新导入，系统会在原应用下追加一个新的文档版本。
          </div>
        </div>
        <div class="import-hero-badge">{{ connectedEnvs.length }} 个可用环境</div>
      </div>

      <div class="import-panel">
        <div class="field-row">
          <label class="field-label">选择环境</label>
          <el-select
            v-model="selectedEnvId"
            placeholder="请选择已连接的环境"
            style="width: 100%"
            @change="onEnvChange"
          >
            <el-option
              v-for="env in connectedEnvs"
              :key="env.id"
              :label="`${env.env_name}${env.is_default ? ' (默认)' : ''}`"
              :value="env.id"
            />
          </el-select>
        </div>

        <div v-if="selectedEnvId" class="app-list-section">
          <div class="search-row">
            <el-input
              v-model="searchText"
              placeholder="搜索应用名称或编码..."
              :prefix-icon="Search"
              clearable
            />
          </div>

          <div class="import-stats">
            <span class="import-stats-item">共 {{ remoteApps.length }} 个应用</span>
            <span class="import-stats-item">已导入 {{ importedCount }} 个</span>
            <span class="import-stats-item">可直接导入 {{ onlineCount }} 个</span>
          </div>

          <div v-if="loading" class="loading-tip">
            <el-icon class="is-loading"><Loading /></el-icon>
            正在加载平台应用...
          </div>

          <div v-else-if="filteredApps.length === 0" class="empty-tip">
            {{ remoteApps.length === 0 ? '该环境下暂无应用' : '无匹配结果' }}
          </div>

          <div v-else class="app-list">
            <div
              v-for="app in filteredApps"
              :key="app.apaas_app_id"
              class="app-item"
              :class="{
                selected: selectedAppId === app.apaas_app_id,
                imported: app.already_imported,
              }"
              @click="selectedAppId = app.apaas_app_id"
            >
              <div class="app-item-left">
                <div class="radio-dot" :class="{ active: selectedAppId === app.apaas_app_id }" />
                <div class="app-item-main">
                  <div class="app-item-head">
                    <div class="app-item-name">{{ app.app_name }}</div>
                    <span class="app-item-tag" :class="app.already_imported ? 'tag-imported' : 'tag-online'">
                      {{ app.already_imported ? '已导入' : '已上线' }}
                    </span>
                  </div>
                  <div v-if="app.app_code" class="app-item-code">{{ app.app_code }}</div>
                  <div v-if="app.description" class="app-item-desc">{{ app.description }}</div>
                </div>
              </div>
              <div class="app-item-action">
                {{ app.already_imported ? '新增版本' : '导入应用' }}
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
import { platformEnvApi, type PlatformEnv, type RemoteApp } from '@/api/platformEnv'
import { applicationApi } from '@/api/application'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [val: boolean]
  imported: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const envs = ref<PlatformEnv[]>([])
const selectedEnvId = ref<number | null>(null)
const remoteApps = ref<RemoteApp[]>([])
const selectedAppId = ref<string>('')
const searchText = ref('')
const loading = ref(false)
const importing = ref(false)

const connectedEnvs = computed(() =>
  envs.value.filter((e) => e.status === 'connected')
)

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

watch(
  () => props.modelValue,
  async (v) => {
    if (v) {
      selectedEnvId.value = null
      remoteApps.value = []
      selectedAppId.value = ''
      searchText.value = ''
      try {
        envs.value = await platformEnvApi.list()
        const def = connectedEnvs.value.find((e) => e.is_default)
        if (def) {
          selectedEnvId.value = def.id
          await onEnvChange(def.id)
        } else if (connectedEnvs.value.length === 1) {
          selectedEnvId.value = connectedEnvs.value[0].id
          await onEnvChange(connectedEnvs.value[0].id)
        }
      } catch (e: any) {
        ElMessage.error('加载环境列表失败')
      }
    }
  }
)

async function onEnvChange(envId: number) {
  selectedAppId.value = ''
  searchText.value = ''
  loading.value = true
  try {
    remoteApps.value = await platformEnvApi.listRemoteApps(envId)
  } catch (e: any) {
    ElMessage.error(e?.message || '加载平台应用失败')
    remoteApps.value = []
  } finally {
    loading.value = false
  }
}

async function doImport() {
  if (!selectedEnvId.value || !selectedAppId.value) return
  importing.value = true
  try {
    await applicationApi.importFromPlatform(selectedEnvId.value, selectedAppId.value)
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
  --import-primary: #6d5dd3;
  --import-primary-soft: #f3f0ff;
  --import-border: #e9e6f7;
  --import-border-strong: #d9d2fb;
  --import-text: #2d3553;
  --import-text-soft: #7f88a8;
  --import-bg: linear-gradient(180deg, #fcfbff 0%, #f6f8ff 100%);
  min-height: 220px;
  color: var(--import-text);
}

.import-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 2px 2px 18px;
}

.import-hero-title {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.3;
  color: #253056;
}

.import-hero-desc {
  margin-top: 6px;
  max-width: 440px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--import-text-soft);
}

.import-hero-badge {
  flex-shrink: 0;
  padding: 7px 12px;
  border-radius: 999px;
  background: var(--import-primary-soft);
  color: var(--import-primary);
  font-size: 12px;
  font-weight: 600;
}

.import-panel {
  padding: 16px;
  border: 1px solid var(--import-border);
  border-radius: 20px;
  background: var(--import-bg);
  box-shadow: 0 18px 40px rgba(109, 93, 211, 0.08);
}

.field-row {
  margin-bottom: 14px;
}

.field-label {
  display: block;
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--import-text-soft);
}

.app-list-section {
  margin-top: 6px;
}

.search-row {
  margin-bottom: 12px;
}

.import-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.import-stats-item {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid var(--import-border);
  color: var(--import-text-soft);
  font-size: 12px;
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
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
}

.app-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  cursor: pointer;
  transition: background 0.2s, box-shadow 0.2s;
  border-bottom: 1px solid rgba(233, 230, 247, 0.8);
}

.app-item:last-child {
  border-bottom: none;
}

.app-item:hover {
  background: #f7f4ff;
}

.app-item.selected {
  background: linear-gradient(180deg, #f2edff 0%, #ece7ff 100%);
  box-shadow: inset 0 0 0 1px var(--import-border-strong);
}

.app-item.imported {
  background-image: linear-gradient(90deg, rgba(109, 93, 211, 0.03) 0%, rgba(109, 93, 211, 0) 100%);
}

.app-item-left {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.app-item-main {
  min-width: 0;
  flex: 1;
}

.app-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.radio-dot {
  width: 16px;
  height: 16px;
  margin-top: 4px;
  border-radius: 50%;
  border: 2px solid #c7c2e8;
  flex-shrink: 0;
  transition: all 0.2s;
}

.radio-dot.active {
  border-color: var(--import-primary);
  background: var(--import-primary);
  box-shadow: inset 0 0 0 3px #fff;
}

.app-item-name {
  font-size: 15px;
  font-weight: 700;
  color: #29345d;
}

.app-item-code {
  margin-top: 4px;
  font-size: 12px;
  color: #8b91ab;
}

.app-item-desc {
  margin-top: 5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.5;
  color: var(--import-text-soft);
}

.app-item-tag {
  flex-shrink: 0;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.tag-online {
  background: #e9f8ec;
  color: #2e7d32;
}

.tag-imported {
  background: #f2f3f8;
  color: #7f88a8;
}

.app-item-action {
  flex-shrink: 0;
  align-self: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--import-primary);
}

.selection-tip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(109, 93, 211, 0.08);
  border: 1px solid rgba(109, 93, 211, 0.14);
}

.selection-tip-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--import-primary);
}

.selection-tip-name {
  font-size: 12px;
  font-weight: 700;
  color: #29345d;
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
  .dialog-footer,
  .app-item,
  .app-item-head {
    flex-direction: column;
    align-items: stretch;
  }

  .import-hero-badge,
  .app-item-action {
    align-self: flex-start;
  }

  .footer-actions {
    justify-content: flex-end;
  }
}
</style>

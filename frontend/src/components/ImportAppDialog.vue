<template>
  <el-dialog
    v-model="visible"
    title="从平台导入应用"
    width="560px"
    destroy-on-close
    @close="$emit('update:modelValue', false)"
  >
    <div class="import-body">
      <!-- 选择环境 -->
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

      <!-- 应用列表 -->
      <div v-if="selectedEnvId" class="app-list-section">
        <div class="search-row">
          <el-input
            v-model="searchText"
            placeholder="搜索应用名称..."
            :prefix-icon="Search"
            clearable
            size="small"
          />
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
            @click="!app.already_imported && (selectedAppId = app.apaas_app_id)"
          >
            <div class="app-item-left">
              <el-icon v-if="app.already_imported" class="check-icon"><Check /></el-icon>
              <div v-else class="radio-dot" :class="{ active: selectedAppId === app.apaas_app_id }" />
              <div>
                <div class="app-item-name">{{ app.app_name }}</div>
                <div v-if="app.app_code" class="app-item-code">{{ app.app_code }}</div>
              </div>
            </div>
            <span class="app-item-tag" :class="app.already_imported ? 'tag-imported' : 'tag-online'">
              {{ app.already_imported ? '已导入' : '已上线' }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button
        type="primary"
        :loading="importing"
        :disabled="!selectedAppId"
        @click="doImport"
      >
        导入选中应用
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Search, Loading, Check } from '@element-plus/icons-vue'
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

const filteredApps = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  if (!q) return remoteApps.value
  return remoteApps.value.filter(
    (a) =>
      a.app_name.toLowerCase().includes(q) ||
      a.app_code.toLowerCase().includes(q)
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
        // 自动选择默认环境
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
  min-height: 200px;
}
.field-row {
  margin-bottom: 16px;
}
.field-label {
  display: block;
  font-size: 13px;
  color: #606266;
  margin-bottom: 6px;
}
.app-list-section {
  margin-top: 8px;
}
.search-row {
  margin-bottom: 10px;
}
.loading-tip,
.empty-tip {
  text-align: center;
  padding: 32px 0;
  color: #909399;
  font-size: 13px;
}
.loading-tip .el-icon {
  margin-right: 6px;
  vertical-align: middle;
}
.app-list {
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}
.app-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.15s;
  border-bottom: 1px solid #f2f3f5;
}
.app-item:last-child {
  border-bottom: none;
}
.app-item:hover:not(.imported) {
  background: #f5f3ff;
}
.app-item.selected {
  background: #ede9fe;
}
.app-item.imported {
  opacity: 0.55;
  cursor: not-allowed;
}
.app-item-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.radio-dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid #c0c4cc;
  flex-shrink: 0;
  transition: all 0.15s;
}
.radio-dot.active {
  border-color: #6d5dd3;
  background: #6d5dd3;
  box-shadow: inset 0 0 0 3px #fff;
}
.check-icon {
  color: #67c23a;
  font-size: 16px;
  flex-shrink: 0;
}
.app-item-name {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}
.app-item-code {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}
.app-item-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  flex-shrink: 0;
}
.tag-online {
  background: #e8f5e9;
  color: #2e7d32;
}
.tag-imported {
  background: #f0f0f0;
  color: #909399;
}
</style>

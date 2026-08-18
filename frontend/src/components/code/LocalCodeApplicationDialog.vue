<template>
  <el-dialog
    v-model="open"
    title="本地项目"
    width="min(560px, calc(100vw - 32px))"
    :close-on-click-modal="!submitting"
    :close-on-press-escape="!submitting"
    :show-close="!submitting"
    destroy-on-close
  >
    <el-form class="local-app-form" label-position="top" @submit.prevent="submit">
      <el-form-item label="项目方式">
        <el-radio-group v-model="directoryMode" data-testid="local-app-directory-mode">
          <el-radio-button value="new_directory">新建项目</el-radio-button>
          <el-radio-button value="existing_directory">打开已有项目</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="应用名称" :error="nameError">
        <el-input
          v-model="appName"
          data-testid="local-app-name"
          maxlength="80"
          autofocus
          placeholder="例如：销售线索评分助手"
          @keydown.enter.prevent
        />
      </el-form-item>

      <el-form-item label="应用编码" :error="codeError">
        <el-input
          v-model="appCode"
          data-testid="local-app-code"
          maxlength="50"
          @input="codeEdited = true"
          @keydown.enter.prevent
        />
      </el-form-item>

      <el-form-item
        :label="directoryMode === 'new_directory' ? '父目录' : '项目目录'"
        :error="workspaceError"
      >
        <div class="local-app-location-row">
          <el-input v-model="selectedDirectory" readonly :loading="loadingWorkspace" />
          <el-button :icon="FolderOpened" :disabled="submitting" title="选择目录" @click="chooseDirectory" />
        </div>
      </el-form-item>

      <el-form-item v-if="directoryMode === 'new_directory'" label="最终项目目录">
        <div class="local-app-project-path" data-testid="local-app-project-path" :title="selectedProjectPath">
          {{ selectedProjectPath || '-' }}
        </div>
      </el-form-item>

      <el-form-item label="初始化项目">
        <el-switch v-model="initializeProject" data-testid="local-app-initialize-project" />
      </el-form-item>

      <p v-if="submitError" class="local-app-submit-error" role="alert">{{ submitError }}</p>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="open = false">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">
        {{ directoryMode === 'new_directory' ? '创建并打开项目' : '打开项目' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { FolderOpened } from '@element-plus/icons-vue'
import {
  codeRuntimeApi,
  type CodeApplication,
  type LocalApplicationDirectoryMode,
} from '@/api/codeRuntime'
import { pickDirectory } from '@/utils/desktop'
import {
  createLocalApplicationCode,
  describeLocalApplicationError,
  localApplicationProjectPath,
  shouldApplyDefaultWorkspace,
  validateLocalApplicationCode,
} from './localApplicationForm'

const props = defineProps<{
  modelValue: boolean
  initialDirectoryMode?: LocalApplicationDirectoryMode
  linkedRemoteApplicationId?: string | null
  linkedRemoteDeploymentId?: string | null
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [application: CodeApplication]
}>()

const open = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})
const appName = ref('')
const appCode = ref('')
const codeEdited = ref(false)
const directoryMode = ref<LocalApplicationDirectoryMode>('new_directory')
const selectedDirectory = ref('')
const initializeProject = ref(false)
const suffix = ref('')
const loadingWorkspace = ref(false)
const submitting = ref(false)
const submitError = ref('')
let defaultWorkspaceRequestId = 0

const nameError = computed(() => {
  const name = appName.value.trim()
  if (!name) return '请输入应用名称'
  if (name.length > 80) return '应用名称不能超过 80 个字符'
  return ''
})
const codeError = computed(() => validateLocalApplicationCode(appCode.value))
const workspaceError = computed(() => selectedDirectory.value.trim()
  ? ''
  : directoryMode.value === 'new_directory' ? '请选择父目录' : '请选择项目目录')
const selectedProjectPath = computed(() => localApplicationProjectPath(
  directoryMode.value,
  selectedDirectory.value,
  appCode.value,
))
const canSubmit = computed(() => !submitting.value
  && (directoryMode.value === 'existing_directory' || !loadingWorkspace.value)
  && !nameError.value && !codeError.value && !workspaceError.value)

watch(appName, name => {
  if (!codeEdited.value) appCode.value = createLocalApplicationCode(name, suffix.value)
})

watch(() => props.modelValue, visible => {
  if (visible) void resetForm()
})

watch(directoryMode, mode => {
  defaultWorkspaceRequestId += 1
  loadingWorkspace.value = false
  initializeProject.value = mode === 'existing_directory'
  selectedDirectory.value = ''
  submitError.value = ''
  if (mode === 'new_directory') void loadDefaultWorkspace()
})

async function resetForm() {
  suffix.value = Date.now().toString(36).slice(-6)
  appName.value = ''
  codeEdited.value = false
  appCode.value = createLocalApplicationCode('', suffix.value)
  const nextDirectoryMode = props.initialDirectoryMode || 'new_directory'
  const directoryModeChanged = directoryMode.value !== nextDirectoryMode
  directoryMode.value = nextDirectoryMode
  initializeProject.value = directoryMode.value === 'existing_directory'
  selectedDirectory.value = ''
  submitError.value = ''
  if (directoryMode.value === 'new_directory' && !directoryModeChanged) await loadDefaultWorkspace()
}

async function loadDefaultWorkspace() {
  if (directoryMode.value !== 'new_directory') return
  const requestId = ++defaultWorkspaceRequestId
  loadingWorkspace.value = true
  try {
    const defaults = await codeRuntimeApi.defaultWorkspace(appCode.value)
    if (shouldApplyDefaultWorkspace(requestId, defaultWorkspaceRequestId, directoryMode.value)) {
      selectedDirectory.value = String(defaults.workspace_root || '').trim()
    }
  } catch (error: any) {
    if (shouldApplyDefaultWorkspace(requestId, defaultWorkspaceRequestId, directoryMode.value)) {
      submitError.value = describeLocalApplicationError(
        error?.response?.data?.detail || error?.message || '默认保存位置加载失败',
      )
    }
  } finally {
    if (requestId === defaultWorkspaceRequestId) loadingWorkspace.value = false
  }
}

async function chooseDirectory() {
  const selected = await pickDirectory(directoryMode.value === 'existing_directory'
    ? '选择已有项目目录'
    : '选择新项目的父目录')
  if (selected) {
    defaultWorkspaceRequestId += 1
    selectedDirectory.value = selected
  }
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  submitError.value = ''
  try {
    const created = await codeRuntimeApi.createApplication({
      app_name: appName.value.trim(),
      app_code: appCode.value.trim(),
      local_application: true,
      directory_mode: directoryMode.value,
      local_workspace_path: selectedProjectPath.value,
      initialize_project: initializeProject.value,
      linked_remote_application_id: props.linkedRemoteApplicationId ?? null,
      linked_remote_deployment_id: props.linkedRemoteDeploymentId ?? null,
    })
    emit('created', created)
    open.value = false
  } catch (error: any) {
    submitError.value = describeLocalApplicationError(
      error?.response?.data?.detail || error?.message || '创建本地应用失败',
    )
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.local-app-form {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.local-app-location-row {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 36px;
  gap: 8px;
}

.local-app-location-row :deep(.el-button) {
  width: 36px;
  padding: 0;
}

.local-app-project-path {
  width: 100%;
  min-height: 34px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-light);
  padding: 7px 11px;
  color: var(--el-text-color-regular);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 18px;
  overflow-wrap: anywhere;
}

.local-app-submit-error {
  margin: 0;
  color: var(--el-color-danger);
  font-size: 12px;
  line-height: 1.5;
}
</style>

<template>
  <el-dialog
    v-model="open"
    title="新建本地应用"
    width="min(560px, calc(100vw - 32px))"
    :close-on-click-modal="!submitting"
    :close-on-press-escape="!submitting"
    :show-close="!submitting"
    destroy-on-close
  >
    <el-form class="local-app-form" label-position="top" @submit.prevent="submit">
      <el-form-item label="应用名称" :error="nameError">
        <el-input
          v-model="appName"
          data-testid="local-app-name"
          maxlength="80"
          autofocus
          placeholder="例如：销售线索评分助手"
        />
      </el-form-item>

      <el-form-item label="应用编码" :error="codeError">
        <el-input
          v-model="appCode"
          data-testid="local-app-code"
          maxlength="50"
          @input="codeEdited = true"
        />
      </el-form-item>

      <el-form-item label="保存位置" :error="workspaceError">
        <div class="local-app-location-row">
          <el-input v-model="workspaceRoot" readonly :loading="loadingWorkspace" />
          <el-button :icon="FolderOpened" :disabled="submitting" title="选择目录" @click="chooseWorkspaceRoot" />
        </div>
      </el-form-item>

      <el-form-item label="最终项目目录">
        <div class="local-app-project-path" data-testid="local-app-project-path" :title="projectPath">
          {{ projectPath || '-' }}
        </div>
      </el-form-item>

      <p v-if="submitError" class="local-app-submit-error" role="alert">{{ submitError }}</p>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="open = false">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">
        创建并打开
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { FolderOpened } from '@element-plus/icons-vue'
import { codeRuntimeApi, type CodeApplication } from '@/api/codeRuntime'
import { pickDirectory } from '@/utils/desktop'
import {
  createLocalApplicationCode,
  joinLocalProjectPath,
  validateLocalApplicationCode,
} from './localApplicationForm'

const props = defineProps<{ modelValue: boolean }>()
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
const workspaceRoot = ref('')
const suffix = ref('')
const loadingWorkspace = ref(false)
const submitting = ref(false)
const submitError = ref('')

const nameError = computed(() => {
  const name = appName.value.trim()
  if (!name) return '请输入应用名称'
  if (name.length > 80) return '应用名称不能超过 80 个字符'
  return ''
})
const codeError = computed(() => validateLocalApplicationCode(appCode.value))
const workspaceError = computed(() => workspaceRoot.value.trim() ? '' : '请选择保存位置')
const projectPath = computed(() => joinLocalProjectPath(workspaceRoot.value, appCode.value))
const canSubmit = computed(() => !submitting.value && !loadingWorkspace.value
  && !nameError.value && !codeError.value && !workspaceError.value)

watch(appName, name => {
  if (!codeEdited.value) appCode.value = createLocalApplicationCode(name, suffix.value)
})

watch(() => props.modelValue, visible => {
  if (visible) void resetForm()
})

async function resetForm() {
  suffix.value = Date.now().toString(36).slice(-6)
  appName.value = ''
  codeEdited.value = false
  appCode.value = createLocalApplicationCode('', suffix.value)
  workspaceRoot.value = ''
  submitError.value = ''
  loadingWorkspace.value = true
  try {
    const defaults = await codeRuntimeApi.defaultWorkspace(appCode.value)
    workspaceRoot.value = String(defaults.workspace_root || '').trim()
  } catch (error: any) {
    submitError.value = error?.response?.data?.detail || error?.message || '默认保存位置加载失败'
  } finally {
    loadingWorkspace.value = false
  }
}

async function chooseWorkspaceRoot() {
  const selected = await pickDirectory('选择本地应用保存位置')
  if (selected) workspaceRoot.value = selected
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
      local_workspace_path: projectPath.value,
    })
    emit('created', created)
    open.value = false
  } catch (error: any) {
    submitError.value = error?.response?.data?.detail || error?.message || '创建本地应用失败'
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

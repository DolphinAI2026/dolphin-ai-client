<template>
  <main class="desktop-setup-page">
    <section class="desktop-setup-shell">
      <header class="desktop-setup-header">
        <h1>{{ showFailure ? 'Dolphin Code 启动失败' : loginOnly ? '重新配置登录服务' : 'Dolphin Code 本地初始化' }}</h1>
        <p v-if="loginOnly">本地存储目录保持不变。</p>
        <p v-else-if="!showFailure">完成登录服务和本地存储设置。</p>
      </header>

      <div v-if="!state" class="desktop-setup-loading" aria-live="polite">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>读取桌面配置</span>
        <p v-if="operationError" class="desktop-message error">{{ operationError }}</p>
      </div>

      <section v-else-if="showFailure" class="desktop-failure" aria-live="assertive">
        <el-alert
          type="error"
          :closable="false"
          show-icon
          :title="state.error?.code || '启动失败'"
          :description="stateErrorMessage"
        />
        <p v-if="operationError" class="desktop-message error">{{ operationError }}</p>
        <div class="desktop-actions start">
          <el-button type="primary" :icon="Refresh" :loading="submitting" @click="retryStart">
            重试启动
          </el-button>
          <el-button :icon="FolderOpened" :disabled="submitting" @click="openLogs">
            打开日志目录
          </el-button>
          <el-button v-if="!loginOnly" :disabled="submitting" @click="reselectRoot">
            重新选择目录
          </el-button>
        </div>
      </section>

      <template v-else>
        <el-steps v-if="!loginOnly" :active="step === 'local_storage' ? 1 : 0" simple class="desktop-steps">
          <el-step title="登录服务" />
          <el-step title="本地存储" />
        </el-steps>

        <el-alert
          v-if="configurationError"
          type="error"
          :closable="false"
          show-icon
          :title="configurationError"
          class="desktop-config-error"
        />

        <section v-if="step === 'login_service' || loginOnly" class="desktop-form-section">
          <div class="desktop-section-heading">
            <h2>选择登录服务</h2>
            <p>登录将通过所选服务完成。</p>
          </div>

          <div class="desktop-service-grid" role="radiogroup" aria-label="登录服务">
            <button
              v-for="service in DESKTOP_LOGIN_SERVICES"
              :key="service.mode"
              type="button"
              class="desktop-service-option"
              :class="{ selected: service.enabled && service.mode === mode }"
              :disabled="!service.enabled || formLocked"
              role="radio"
              :aria-checked="service.enabled && service.mode === mode"
              @click="selectService(service)"
            >
              <strong>{{ service.label }}</strong>
              <small v-if="!service.enabled">暂未开放</small>
            </button>
          </div>

          <el-form label-position="top" class="desktop-form" @submit.prevent>
            <el-form-item label="服务地址" :error="urlTouched ? urlError : ''">
              <el-input
                v-model="baseUrl"
                :disabled="formLocked"
                autocomplete="url"
                placeholder="https://example.com"
                @input="onBaseUrlInput"
                @blur="urlTouched = true"
              />
            </el-form-item>
          </el-form>

          <p
            v-if="connectionMessage"
            class="desktop-message"
            :class="{ error: connectionFailed }"
            aria-live="polite"
          >
            {{ connectionMessage }}
          </p>
        </section>

        <section v-else class="desktop-form-section">
          <div class="desktop-section-heading">
            <h2>选择本地根目录</h2>
            <p>应用和运行数据将存放在此目录下。</p>
          </div>

          <el-form label-position="top" class="desktop-form" @submit.prevent>
            <el-form-item label="本地根目录" :error="rootTouched ? rootError : ''">
              <el-input
                v-model="rootDir"
                :disabled="formLocked"
                placeholder="选择 Dolphin Code 本地根目录"
                @input="rootTouched = true"
                @blur="rootTouched = true"
              >
                <template #append>
                  <el-button
                    :icon="FolderOpened"
                    :disabled="formLocked"
                    title="选择目录"
                    aria-label="选择目录"
                    @click="chooseRoot"
                  />
                </template>
              </el-input>
            </el-form-item>
          </el-form>

          <div class="desktop-path-preview" aria-label="本地目录预览">
            <code>{{ applicationsPath }}</code>
            <code>{{ appDataPath }}</code>
          </div>

          <el-form label-position="top" class="desktop-form desktop-workspace-entry-form">
            <el-form-item label="工作台入口">
              <el-radio-group
                v-model="workspaceScope"
                :disabled="formLocked"
                class="desktop-workspace-entry-options"
                aria-label="工作台入口"
              >
                <el-radio-button
                  v-for="option in DESKTOP_WORKSPACE_ENTRY_OPTIONS"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>
        </section>

        <p v-if="operationError" class="desktop-message error" aria-live="polite">
          {{ operationError }}
        </p>

        <footer class="desktop-actions">
          <div v-if="isStarting" class="desktop-progress" aria-live="polite">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>{{ progressLabel }}</span>
          </div>

          <template v-else-if="step === 'login_service' || loginOnly">
            <el-button :loading="connectionTesting" :disabled="submitting" @click="testConnection">
              测试连接
            </el-button>
            <el-button
              type="primary"
              :loading="submitting"
              :disabled="Boolean(urlError)"
              @click="loginOnly ? submitSetup() : goToStorage()"
            >
              {{ loginOnly ? '保存并重新登录' : '下一步' }}
            </el-button>
          </template>

          <template v-else>
            <el-button :disabled="submitting" @click="goBack">上一步</el-button>
            <el-button
              type="primary"
              :loading="submitting"
              :disabled="Boolean(rootError) || workspaceScope === null"
              @click="submitSetup"
            >
              保存并进入登录
            </el-button>
          </template>
        </footer>
      </template>
    </section>
  </main>
</template>

<script lang="ts">
function containsJwt(value: string): boolean {
  return value.split(/[\s"'(),;[\]{}]+/).some((candidate) => {
    const parts = candidate.split('.')
    return parts.length === 3
      && parts[0].startsWith('eyJ')
      && parts.every(part => part.length > 0 && /^[A-Za-z0-9_-]+$/.test(part))
  })
}

function normalizeSensitiveKey(key: string): string {
  return key.replace(/[^A-Za-z0-9]/g, '').toLowerCase()
}

function isSensitiveKey(key: string): boolean {
  const normalized = normalizeSensitiveKey(key)
  return normalized === 'authorization'
    || normalized.endsWith('password')
    || normalized.endsWith('token')
    || normalized.endsWith('apikey')
    || normalized.endsWith('secret')
    || normalized.endsWith('encryptionkey')
    || normalized.endsWith('privatekey')
    || normalized.endsWith('authenticationresponse')
}

function containsSensitiveAssignment(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const match = value.slice(index).match(/^["']?([A-Za-z0-9 _-]{1,80})["']?\s*[:=]/)
    if (match && isSensitiveKey(match[1])) return true
  }
  return false
}

function containsSensitiveUrl(value: string): boolean {
  for (const match of value.matchAll(/https?:\/\/[^\s"'<>]+/gi)) {
    const candidate = match[0].replace(/[,;\)\]\}]+$/, '')
    try {
      const url = new URL(candidate)
      if (url.username || url.password) return true
      for (const key of url.searchParams.keys()) {
        if (isSensitiveKey(key)) return true
      }
    } catch {
      // Malformed URLs are handled as ordinary text.
    }
  }
  return false
}

function containsNonJsonSensitiveValue(value: string): boolean {
  return /traceback/i.test(value)
    || containsSensitiveAssignment(value)
    || /\bbearer\s+\S+/i.test(value)
    || containsJwt(value)
    || containsSensitiveUrl(value)
}

function jsonContainsSensitiveValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(jsonContainsSensitiveValue)
  if (value && typeof value === 'object') {
    return Object.entries(value).some(([key, item]) => (
      isSensitiveKey(key) || jsonContainsSensitiveValue(item)
    ))
  }
  return typeof value === 'string' && containsNonJsonSensitiveValue(value)
}

function containsSensitiveValue(value: string): boolean {
  try {
    return jsonContainsSensitiveValue(JSON.parse(value))
  } catch {
    return containsNonJsonSensitiveValue(value)
  }
}

export function safeDesktopFailureMessage(error: unknown, fallback: string): string {
  const raw = typeof error === 'string'
    ? error
    : error && typeof error === 'object' && 'message' in error
      ? String((error as { message?: unknown }).message ?? '')
      : ''
  if (!raw.trim() || containsSensitiveValue(raw)) return fallback
  const firstLine = raw.split(/\r?\n/).find(line => line.trim())?.trim() ?? ''
  return firstLine.slice(0, 240)
}
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { FolderOpened, Loading, Refresh } from '@element-plus/icons-vue'
import {
  DESKTOP_LOGIN_SERVICES,
  DESKTOP_WORKSPACE_ENTRY_OPTIONS,
  buildDesktopSetupInput,
  getDesktopState,
  openDesktopPath,
  pickDirectory,
  retryDesktopStart,
  resolveDesktopSetupView,
  saveDesktopSetup,
  testDesktopService,
  transitionDesktopSetup,
  updateDesktopLogin,
  type DesktopSetupEvent,
  type DesktopSetupMachineState,
  type DesktopSetupStep,
  type DesktopLoginMode,
  type DesktopLoginServiceOption,
  type DesktopPhase,
  type DesktopStateSnapshot,
  type DesktopWorkspaceEntryScope,
} from '@/utils/desktop'

const state = ref<DesktopStateSnapshot | null>(null)
const step = ref<DesktopSetupStep>('login_service')
const mode = ref<DesktopLoginMode>('control_plane')
const baseUrl = ref('https://om-demo.dfy.definesys.cn')
const rootDir = ref('')
const workspaceScope = ref<DesktopWorkspaceEntryScope | null>(null)
const submitting = ref(false)
const connectionTesting = ref(false)

const urlTouched = ref(false)
const rootTouched = ref(false)
const operationError = ref('')
const connectionMessage = ref('')
const connectionFailed = ref(false)
const editingFailedConfig = ref(false)
const editedModes = new Set<DesktopLoginMode>()
const serviceUrls: Record<DesktopLoginMode, string> = {
  control_plane: 'https://om-demo.dfy.definesys.cn',
  apaas: 'https://apaas-trial.definesys.cn/backend',
}
const phaseLabels: Partial<Record<DesktopPhase, string>> = {
  saving_config: '保存配置',
  starting_runtime: '启动本地环境',
  starting_sidecar: '打开登录页',
}

let formHydrated = false
let polling = false
let disposed = false
let pollTimer: number | undefined

const viewDecision = computed(() => state.value ? resolveDesktopSetupView(state.value) : null)
const loginOnly = computed(() => viewDecision.value?.directoryEditable === false)
const isStarting = computed(() => ['saving_config', 'starting_runtime', 'starting_sidecar']
  .includes(state.value?.phase ?? ''))
const showFailure = computed(() => (
  viewDecision.value?.recovery === 'retry_start'
  && !editingFailedConfig.value
))
const configurationError = computed(() => {
  if (viewDecision.value?.recovery !== 'edit_config') return ''
  return safeMessage(state.value?.error?.message, '桌面配置无效，请检查后重试')
})
const stateErrorMessage = computed(() => safeMessage(
  state.value?.error?.message,
  '本地环境未能启动，请重试或查看日志',
))
const progressLabel = computed(() => state.value ? phaseLabels[state.value.phase] ?? '' : '')
const urlError = computed(() => validateServiceUrl(baseUrl.value))
const rootError = computed(() => rootDir.value.trim() ? '' : '请选择本地根目录')
const applicationsPath = computed(() => childPath(rootDir.value, 'applications'))
const appDataPath = computed(() => childPath(rootDir.value, '.appdata'))
const formLocked = computed(() => submitting.value || isStarting.value)

const safeMessage = safeDesktopFailureMessage

function validateServiceUrl(value: string): string {
  try {
    const url = new URL(value.trim())
    if (!['http:', 'https:'].includes(url.protocol)
      || !url.hostname
      || url.username
      || url.password
      || url.hash) {
      return '请输入无凭据、无 fragment 的 HTTP(S) 绝对 URL'
    }
    return ''
  } catch {
    return '请输入有效的 HTTP(S) 绝对 URL'
  }
}

function childPath(root: string, child: string): string {
  const normalizedRoot = root.trim().replace(/[\\/]+$/, '')
  if (!normalizedRoot) return `<root>/${child}`
  const separator = normalizedRoot.includes('\\') && !normalizedRoot.includes('/') ? '\\' : '/'
  return `${normalizedRoot}${separator}${child}`
}

function hydrateForm(snapshot: DesktopStateSnapshot) {
  rootDir.value = resolveDesktopSetupView(snapshot).rootDir
  if (snapshot.config) {
    mode.value = snapshot.config.login.mode
    baseUrl.value = snapshot.config.login.base_url
    workspaceScope.value = snapshot.config.workspace_entry_scope
    serviceUrls[mode.value] = baseUrl.value
    editedModes.add(mode.value)
  }
  formHydrated = true
}

function machineState(): DesktopSetupMachineState {
  return {
    scope: state.value?.setup_scope ?? 'full',
    step: step.value,
  }
}

function schedulePolling(event: Extract<DesktopSetupEvent, 'poll_tick' | 'ready'>) {
  stopPolling()
  if (disposed) return
  const effect = transitionDesktopSetup(machineState(), event)
  if (effect.stopPolling || effect.pollAfterMs == null) return
  pollTimer = window.setTimeout(() => void refreshState(), effect.pollAfterMs)
}

function applySnapshot(snapshot: DesktopStateSnapshot) {
  state.value = snapshot
  if (!formHydrated) hydrateForm(snapshot)
  if (snapshot.phase !== 'failed') editingFailedConfig.value = false
  schedulePolling(snapshot.phase === 'ready' ? 'ready' : 'poll_tick')
}

function stopPolling() {
  if (pollTimer == null) return
  window.clearTimeout(pollTimer)
  pollTimer = undefined
}

async function refreshState() {
  if (polling || disposed) return
  polling = true
  try {
    const wasWaitingForState = !state.value
    const snapshot = await getDesktopState()
    if (disposed) return
    applySnapshot(snapshot)
    if (wasWaitingForState) operationError.value = ''
  } catch (error) {
    if (disposed) return
    if (!state.value) operationError.value = safeMessage(error, '无法读取桌面初始化状态，正在重试')
    schedulePolling('poll_tick')
  } finally {
    polling = false
  }
}

function selectService(service: DesktopLoginServiceOption) {
  if (!service.enabled || (service.mode !== 'control_plane' && service.mode !== 'apaas')) return
  mode.value = service.mode
  if (!editedModes.has(service.mode)) serviceUrls[service.mode] = service.defaultUrl
  baseUrl.value = serviceUrls[service.mode]
  urlTouched.value = false
  connectionMessage.value = ''
  operationError.value = ''
}

function onBaseUrlInput(value: string) {
  serviceUrls[mode.value] = value
  editedModes.add(mode.value)
  connectionMessage.value = ''
}

async function testConnection() {
  urlTouched.value = true
  connectionMessage.value = ''
  operationError.value = ''
  if (urlError.value) return
  connectionTesting.value = true
  try {
    await testDesktopService({ mode: mode.value, base_url: baseUrl.value.trim() })
    connectionFailed.value = false
    connectionMessage.value = '连接成功'
  } catch (error) {
    connectionFailed.value = true
    connectionMessage.value = safeMessage(error, '连接测试失败')
  } finally {
    connectionTesting.value = false
  }
}

function goToStorage() {
  urlTouched.value = true
  if (urlError.value) return
  step.value = transitionDesktopSetup(machineState(), 'next').step
  operationError.value = ''
}

function goBack() {
  step.value = transitionDesktopSetup(machineState(), 'back').step
}

async function chooseRoot() {
  const effect = transitionDesktopSetup(machineState(), 'pick_directory')
  if (effect.pickerRequests !== 1) return
  operationError.value = ''
  try {
    const selected = await pickDirectory('选择 Dolphin Code 本地根目录')
    if (selected) {
      rootDir.value = selected
      rootTouched.value = true
    }
  } catch (error) {
    operationError.value = safeMessage(error, '无法打开目录选择器')
  }
}

async function submitSetup() {
  urlTouched.value = true
  if (urlError.value) return
  if (!loginOnly.value) {
    rootTouched.value = true
    if (rootError.value || workspaceScope.value === null) return
  }

  submitting.value = true
  editingFailedConfig.value = false
  operationError.value = ''
  const login = { mode: mode.value, base_url: baseUrl.value.trim() }
  try {
    if (loginOnly.value) {
      applySnapshot(await updateDesktopLogin(login))
    } else {
      const scope = workspaceScope.value
      if (!scope) return
      applySnapshot(await saveDesktopSetup(buildDesktopSetupInput(
        rootDir.value.trim(),
        mode.value,
        baseUrl.value.trim(),
        scope,
      )))
    }
  } catch (error) {
    operationError.value = safeMessage(error, '无法保存桌面配置')
  } finally {
    submitting.value = false
  }
}

async function retryStart() {
  submitting.value = true
  editingFailedConfig.value = false
  operationError.value = ''
  try {
    applySnapshot(await retryDesktopStart())
  } catch (error) {
    operationError.value = safeMessage(error, '无法重试启动')
  } finally {
    submitting.value = false
  }
}

async function openLogs() {
  submitting.value = true
  operationError.value = ''
  try {
    await openDesktopPath('logs')
  } catch (error) {
    operationError.value = safeMessage(error, '无法打开日志目录')
  } finally {
    submitting.value = false
  }
}

async function reselectRoot() {
  editingFailedConfig.value = true
  step.value = transitionDesktopSetup(machineState(), 'next').step
  await chooseRoot()
}

onMounted(() => {
  void refreshState()
})

function disposePolling() {
  disposed = true
  stopPolling()
}

onBeforeUnmount(disposePolling)
</script>

<style scoped>
.desktop-setup-page {
  min-height: 100%;
  padding: 48px 24px;
  display: grid;
  place-items: start center;
  background: var(--bg, #f5f6f8);
  color: var(--text, #1f2329);
}

.desktop-setup-shell {
  width: min(680px, 100%);
  padding: 30px;
  border: 1px solid var(--line, #dcdfe6);
  border-radius: 8px;
  background: var(--surface, #fff);
  box-shadow: 0 12px 32px rgba(31, 35, 41, 0.08);
}

.desktop-setup-header h1,
.desktop-setup-header p,
.desktop-section-heading h2,
.desktop-section-heading p,
.desktop-message {
  margin: 0;
}

.desktop-setup-header h1 {
  font-size: 22px;
  line-height: 30px;
  font-weight: 650;
  letter-spacing: 0;
}

.desktop-setup-header p,
.desktop-section-heading p {
  margin-top: 3px;
  color: var(--text-3, #86909c);
  font-size: 12px;
  line-height: 18px;
}

.desktop-steps,
.desktop-config-error,
.desktop-failure {
  margin-top: 28px;
}

.desktop-form-section {
  margin-top: 26px;
}

.desktop-section-heading h2 {
  font-size: 16px;
  line-height: 24px;
  font-weight: 650;
  letter-spacing: 0;
}

.desktop-service-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.desktop-service-option {
  min-height: 56px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid var(--line, #dcdfe6);
  border-radius: 8px;
  background: var(--surface, #fff);
  color: var(--text, #1f2329);
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.desktop-service-option:hover:not(:disabled) {
  background: var(--surface-2, #f7f8fa);
}

.desktop-service-option:focus-visible {
  outline: 2px solid var(--brand-ring, #c9d2ff);
  outline-offset: 2px;
}

.desktop-service-option.selected {
  border-color: var(--brand, #3555d3);
  box-shadow: 0 0 0 2px var(--brand-ring, #c9d2ff);
}

.desktop-service-option:disabled {
  background: var(--surface-2, #f7f8fa);
  color: var(--text-4, #a8abb2);
  cursor: not-allowed;
}

.desktop-service-option strong {
  font-size: 14px;
  line-height: 20px;
  font-weight: 600;
}

.desktop-service-option small {
  font-size: 11px;
  line-height: 16px;
}

.desktop-form {
  margin-top: 18px;
}

.desktop-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.desktop-path-preview {
  margin-top: 14px;
  padding: 12px 14px;
  display: grid;
  gap: 7px;
  border: 1px solid var(--line, #dcdfe6);
  border-radius: 8px;
  background: var(--surface-2, #f7f8fa);
}

.desktop-path-preview code {
  color: var(--text-2, #4e5969);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  line-height: 18px;
  overflow-wrap: anywhere;
}

.desktop-actions {
  min-height: 40px;
  margin-top: 26px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.desktop-actions.start {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.desktop-progress,
.desktop-setup-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: var(--text-2, #4e5969);
  font-size: 13px;
}

.desktop-progress {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--line, #dcdfe6);
  border-radius: 8px;
  background: var(--surface-2, #f7f8fa);
}

.desktop-setup-loading {
  min-height: 220px;
  flex-direction: column;
}

.desktop-message {
  margin-top: 12px;
  color: var(--ok, #16803c);
  font-size: 12px;
  line-height: 18px;
  overflow-wrap: anywhere;
}

.desktop-message.error {
  color: var(--err, #c73838);
}

@media (max-width: 640px) {
  .desktop-setup-page {
    padding: 20px 12px;
  }

  .desktop-setup-shell {
    padding: 22px 18px;
  }

  .desktop-service-grid {
    grid-template-columns: 1fr;
  }

  .desktop-actions:not(.start) {
    align-items: stretch;
    flex-direction: column-reverse;
  }

  .desktop-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>

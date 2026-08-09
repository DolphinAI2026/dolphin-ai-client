<template>
  <main class="desktop-setup-page">
    <section class="desktop-setup-shell">
      <header class="desktop-setup-header">
        <div class="desktop-brand-mark">D</div>
        <div>
          <h1>{{ showFailure ? 'Dolphin Code 启动失败' : '连接 Dolphin Code' }}</h1>
          <p>{{ showFailure ? '桌面服务没有完成启动，请重试或修改远程地址。' : '输入一次远程服务地址，桌面端会自动发现认证和 Builder / Code 能力。' }}</p>
        </div>
      </header>

      <div v-if="!state" class="desktop-setup-loading" aria-live="polite">
        <el-icon class="is-loading"><Loading /></el-icon><span>读取桌面配置</span>
      </div>

      <section v-else-if="showFailure" class="desktop-failure" aria-live="assertive">
        <el-alert type="error" :closable="false" show-icon :title="state.error?.code || '启动失败'" :description="stateErrorMessage" />
        <p v-if="operationError" class="desktop-message error">{{ operationError }}</p>
        <footer class="desktop-actions">
          <el-button type="primary" :icon="Refresh" :loading="submitting" @click="retryStart">重试启动</el-button>
          <el-button :icon="Document" :disabled="submitting" @click="openLogs">打开日志目录</el-button>
        </footer>
      </section>

      <template v-else>
        <el-form label-position="top" class="desktop-form" @submit.prevent>
          <el-form-item label="远程服务地址" :error="urlTouched ? urlError : ''">
            <el-input v-model="serviceUrl" :disabled="formLocked" autocomplete="url" placeholder="输入完整 Control Plane 或仅 aPaaS Builder 地址" @blur="urlTouched = true" />
            <DesktopServiceExamples />
          </el-form-item>
        </el-form>

        <section v-if="discovery" class="desktop-discovery-card" aria-live="polite">
          <div class="discovery-title"><span class="status-dot" />{{ discovery.platform.name }}</div>
          <div class="discovery-meta">{{ discovery.platform.type === 'apaas_builder' ? 'aPaaS Builder 服务' : 'Control Plane 服务' }} · {{ discovery.deployment_id }}</div>
          <div class="discovery-products">
            <el-tag v-if="discovery.products.builder.enabled" type="success">Builder</el-tag>
            <el-tag v-if="discovery.products.code.enabled" type="info">Code</el-tag>
            <span class="local-ai-note">本地模型、MCP、Skill、知识库默认开启</span>
          </div>
        </section>

        <p v-if="connectionMessage" class="desktop-message" :class="{ error: connectionFailed }">{{ connectionMessage }}</p>
        <p v-if="operationError" class="desktop-message error">{{ operationError }}</p>

        <footer class="desktop-actions">
          <div v-if="isStarting" class="desktop-progress" aria-live="polite"><el-icon class="is-loading"><Loading /></el-icon><span>{{ progressLabel }}</span></div>
          <template v-else>
            <el-button :loading="discovering" :disabled="submitting" @click="discoverService">{{ discovery ? '重新发现' : '连接并继续' }}</el-button>
            <el-button v-if="discovery" type="primary" :loading="submitting" :disabled="Boolean(urlError)" @click="submitSetup">保存并打开登录</el-button>
          </template>
        </footer>
      </template>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Document, Loading, Refresh } from '@element-plus/icons-vue'
import DesktopServiceExamples from '@/components/desktop/DesktopServiceExamples.vue'
import {
  buildDesktopSetupInput,
  discoverDesktopService,
  desktopErrorMessage,
  getDesktopState,
  openDesktopPath,
  retryDesktopStart,
  saveDesktopSetup,
  type DesktopDiscoveryDocument,
  type DesktopLoginMode,
  type DesktopPhase,
  type DesktopStateSnapshot,
} from '@/utils/desktop'

const state = ref<DesktopStateSnapshot | null>(null)
const router = useRouter()
const serviceUrl = ref('')
const discovery = ref<DesktopDiscoveryDocument | null>(null)
const submitting = ref(false)
const discovering = ref(false)
const urlTouched = ref(false)
const operationError = ref('')
const connectionMessage = ref('')
const connectionFailed = ref(false)
const disposed = ref(false)
let timer: number | undefined

const isStarting = computed(() => ['saving_config', 'starting_runtime', 'starting_sidecar'].includes(state.value?.phase || ''))
const formLocked = computed(() => submitting.value || discovering.value || isStarting.value)
const showFailure = computed(() => state.value?.phase === 'failed')
const progressLabel = computed(() => {
  const phase = state.value?.phase
  if (phase === 'saving_config') return '保存连接配置'
  if (phase === 'starting_runtime') return '准备桌面服务'
  if (phase === 'starting_sidecar') return '打开远程登录'
  return '准备桌面服务'
})
const stateErrorMessage = computed(() => state.value?.error?.message || '桌面服务未能启动')
const urlError = computed(() => validateServiceUrl(serviceUrl.value))

function validateServiceUrl(value: string): string {
  try {
    const url = new URL(value.trim())
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password || url.hash) return '请输入无凭据的 HTTP(S) 地址'
    return ''
  } catch { return '请输入有效的 HTTP(S) 地址' }
}

function applySnapshot(snapshot: DesktopStateSnapshot) {
  state.value = snapshot
  if (snapshot.config) {
    serviceUrl.value = snapshot.config.discovery_url || snapshot.config.login.base_url
    discovery.value = snapshot.config.discovery || discovery.value
  }
  if (isStarting.value && !disposed.value) timer = window.setTimeout(refreshState, 500)
}

async function refreshState() {
  if (disposed.value) return
  try { applySnapshot(await getDesktopState()) } catch { timer = window.setTimeout(refreshState, 800) }
}

async function discoverService() {
  urlTouched.value = true
  connectionMessage.value = ''
  operationError.value = ''
  if (urlError.value) return
  discovering.value = true
  try {
    discovery.value = await discoverDesktopService(serviceUrl.value.trim())
    connectionFailed.value = false
    connectionMessage.value = '已发现远程平台配置'
  } catch (error) {
    connectionFailed.value = true
    connectionMessage.value = desktopErrorMessage(error, '无法连接远程服务')
  } finally { discovering.value = false }
}

async function submitSetup() {
  if (!discovery.value || urlError.value) return
  submitting.value = true
  operationError.value = ''
  const mode: DesktopLoginMode = discovery.value.auth.provider === 'apaas' ? 'apaas' : 'control_plane'
  try {
    const snapshot = await saveDesktopSetup(buildDesktopSetupInput(
      state.value?.default_root_dir || '', mode, discovery.value.auth.login_url, 'both', serviceUrl.value.trim(), discovery.value,
    ))
    applySnapshot(snapshot)
    // Web preview completes setup synchronously; the native backend navigates
    // after its sidecar becomes ready, so only navigate here for an immediate
    // ready result.
    if (snapshot.phase === 'ready') await router.replace('/login')
  } catch (error) { operationError.value = desktopErrorMessage(error, '无法保存桌面配置') }
  finally { submitting.value = false }
}

async function retryStart() {
  submitting.value = true
  try { applySnapshot(await retryDesktopStart()) } catch (error) { operationError.value = desktopErrorMessage(error, '无法重试启动') }
  finally { submitting.value = false }
}

async function openLogs() {
  try { await openDesktopPath('logs') } catch { operationError.value = '无法打开日志目录' }
}

onMounted(() => { void refreshState() })
onBeforeUnmount(() => { disposed.value = true; if (timer) window.clearTimeout(timer) })
</script>

<style scoped>
.desktop-setup-page { min-height: 100%; padding: 56px 24px; display: grid; place-items: start center; background: var(--bg, #f5f6f8); color: var(--text, #1f2329); }
.desktop-setup-shell { width: min(620px, 100%); padding: 32px; border: 1px solid var(--line, #dcdfe6); border-radius: 10px; background: var(--surface, #fff); box-shadow: 0 12px 32px rgba(31,35,41,.08); }
.desktop-setup-header { display: flex; gap: 14px; align-items: center; margin-bottom: 28px; }
.desktop-brand-mark { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 9px; background: var(--brand, #245bdb); color: #fff; font-weight: 700; }
h1 { margin: 0; font-size: 22px; line-height: 30px; } p { margin: 4px 0 0; color: var(--text-3, #86909c); font-size: 12px; line-height: 18px; }
.desktop-form { margin-bottom: 18px; } .desktop-discovery-card { padding: 16px; border: 1px solid var(--line, #e5e6eb); border-radius: 8px; background: var(--surface-2, #f7f8fa); }
.discovery-title { font-size: 15px; font-weight: 650; } .status-dot { display: inline-block; width: 8px; height: 8px; margin-right: 7px; border-radius: 50%; background: #22c55e; }
.discovery-meta { margin-top: 5px; color: var(--text-3, #86909c); font-size: 12px; } .discovery-products { margin-top: 12px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.local-ai-note { color: var(--text-2, #4e5969); font-size: 12px; } .desktop-message { margin: 12px 0; font-size: 12px; } .desktop-message.error { color: var(--danger, #ef4444); }
.desktop-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 24px; } .desktop-progress { display: flex; align-items: center; gap: 8px; margin-right: auto; color: var(--text-2, #4e5969); font-size: 13px; }
.desktop-setup-loading { min-height: 160px; display: flex; justify-content: center; align-items: center; gap: 8px; color: var(--text-3, #86909c); }
@media (max-width: 640px) { .desktop-setup-page { padding: 28px 16px; } .desktop-setup-shell { padding: 24px 18px; } .desktop-actions { flex-wrap: wrap; } .desktop-actions .el-button { flex: 1; } }
</style>

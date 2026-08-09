<template>
  <BuilderFrame :breadcrumbs="[{ label: '桌面设置' }]">
    <main class="desktop-settings-page">
      <div class="desktop-settings-content">
        <header class="desktop-settings-header"><h1>桌面设置</h1><p>远程平台负责认证、租户、应用和会话；本地只补充 AI 资源。</p></header>
        <div v-if="loading" class="desktop-settings-loading"><el-icon class="is-loading"><Loading /></el-icon>读取桌面配置</div>
        <el-alert v-else-if="loadError" type="error" :closable="false" show-icon :title="loadError" />
        <div v-else class="desktop-settings-form">
          <section class="desktop-settings-section">
            <div class="desktop-settings-section-copy"><h2>远程连接</h2><p>输入地址后重新发现，认证方式和产品入口由远程服务决定。</p></div>
            <el-form label-position="top" class="desktop-field-form" @submit.prevent>
              <el-form-item label="远程服务地址" :error="urlTouched ? urlError : ''">
                <el-input v-model="serviceUrl" :disabled="saving || discovering" placeholder="输入完整 Control Plane 或仅 aPaaS Builder 地址" @blur="urlTouched = true" />
                <DesktopServiceExamples />
              </el-form-item>
            </el-form>
            <div v-if="discovery" class="discovery-summary">
              <strong>{{ discovery.platform.name }}</strong>
              <span>{{ discovery.platform.type === 'apaas_builder' ? 'aPaaS Builder' : 'Control Plane' }}</span>
              <span>{{ discovery.auth.provider === 'apaas' ? 'aPaaS 认证' : '平台认证' }}</span>
              <span>Builder {{ discovery.products.builder.enabled ? '已启用' : '未启用' }}</span>
              <span>Code {{ discovery.products.code.enabled ? '已启用' : '未启用' }}</span>
            </div>
            <p v-if="operationError" class="desktop-settings-error">{{ operationError }}</p>
            <div class="desktop-section-actions"><el-button :loading="discovering" :disabled="saving || Boolean(urlError)" @click="rediscover">重新发现</el-button><el-button type="primary" :loading="saving" :disabled="!discovery || Boolean(urlError)" @click="saveConnection">保存并重新连接</el-button></div>
          </section>

          <section class="desktop-settings-section">
            <div class="desktop-settings-section-copy"><h2>本地 AI</h2><p>本地模型、MCP、Skill、知识库保存在桌面 SQLite，只能由本机工程使用。</p></div>
            <div class="local-ai-row"><el-switch v-model="localAiEnabled" :disabled="saving" /><span>启用本地 AI 资源</span><el-tag type="success">默认开启</el-tag></div>
            <div class="local-ai-kinds"><el-tag v-for="kind in localAiKinds" :key="kind">{{ kind }}</el-tag></div>
          </section>

          <section class="desktop-settings-section">
            <div class="desktop-settings-section-copy"><h2>存储与诊断</h2><p>目录由桌面端固定管理，不要求 Git 或用户工作区。</p></div>
            <el-input :model-value="rootDir" readonly />
            <div class="desktop-path-actions"><el-button :icon="FolderOpened" :loading="openingPath === 'root'" @click="openPath('root')">打开数据目录</el-button><el-button :icon="Document" :loading="openingPath === 'logs'" @click="openPath('logs')">打开日志目录</el-button></div>
          </section>
        </div>
      </div>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Document, FolderOpened, Loading } from '@element-plus/icons-vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import DesktopServiceExamples from '@/components/desktop/DesktopServiceExamples.vue'
import {
  buildDesktopSetupInput,
  discoverDesktopService,
  desktopErrorMessage,
  getDesktopState,
  openDesktopPath,
  saveDesktopSetup,
  type DesktopDiscoveryDocument,
  type DesktopPathKind,
  type DesktopStateSnapshot,
} from '@/utils/desktop'

const snapshot = ref<DesktopStateSnapshot | null>(null)
const serviceUrl = ref('')
const discovery = ref<DesktopDiscoveryDocument | null>(null)
const rootDir = ref('')
const localAiEnabled = ref(true)
const loading = ref(true)
const saving = ref(false)
const discovering = ref(false)
const openingPath = ref<DesktopPathKind | null>(null)
const loadError = ref('')
const operationError = ref('')
const urlTouched = ref(false)
const localAiKinds = ['模型', 'MCP', 'Skill', '知识库']
const urlError = computed(() => validateServiceUrl(serviceUrl.value))

function validateServiceUrl(value: string): string {
  try { const url = new URL(value.trim()); return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password && !url.hash ? '' : '请输入有效的 HTTP(S) 地址' } catch { return '请输入有效的 HTTP(S) 地址' }
}

async function loadSettings() {
  loading.value = true
  try {
    const value = await getDesktopState()
    snapshot.value = value
    const config = value.config
    if (!config) { loadError.value = '桌面配置尚未完成，请先完成首次初始化'; return }
    rootDir.value = config.root_dir || value.default_root_dir
    serviceUrl.value = config.discovery_url || config.login.base_url
    discovery.value = config.discovery || null
    localAiEnabled.value = config.local_ai_enabled !== false
  } catch { loadError.value = '无法读取桌面配置，请稍后重试' }
  finally { loading.value = false }
}

async function rediscover() {
  urlTouched.value = true
  if (urlError.value) return
  discovering.value = true
  operationError.value = ''
  try { discovery.value = await discoverDesktopService(serviceUrl.value.trim()) } catch (error) { operationError.value = desktopErrorMessage(error, '无法连接远程服务') }
  finally { discovering.value = false }
}

async function saveConnection() {
  if (!discovery.value || urlError.value) return
  saving.value = true
  operationError.value = ''
  try {
    const mode = discovery.value.auth.provider === 'apaas' ? 'apaas' : 'control_plane'
    snapshot.value = await saveDesktopSetup(buildDesktopSetupInput(rootDir.value || snapshot.value?.default_root_dir || '', mode, discovery.value.auth.login_url, 'both', serviceUrl.value.trim(), discovery.value, localAiEnabled.value))
  } catch (error) { operationError.value = desktopErrorMessage(error, '保存连接失败') }
  finally { saving.value = false }
}

async function openPath(kind: DesktopPathKind) { openingPath.value = kind; try { await openDesktopPath(kind) } catch { operationError.value = '无法打开目录' } finally { openingPath.value = null } }
onMounted(() => { void loadSettings() })
</script>

<style scoped>
.desktop-settings-page { flex: 1; min-height: 0; overflow-y: auto; padding: 32px 28px 48px; color: var(--text); background: var(--bg); }
.desktop-settings-content { width: min(760px, 100%); margin: 0 auto; }.desktop-settings-header h1 { margin: 0; font-size: 22px; line-height: 30px; }.desktop-settings-header p { margin: 4px 0 0; color: var(--text-3); font-size: 12px; }
.desktop-settings-form { margin-top: 28px; border-top: 1px solid var(--line); }.desktop-settings-section { padding: 24px 0; border-bottom: 1px solid var(--line); }.desktop-settings-section-copy h2 { margin: 0; font-size: 15px; }.desktop-settings-section-copy p { margin: 4px 0 16px; color: var(--text-3); font-size: 12px; }
.desktop-field-form { width: min(560px, 100%); }.discovery-summary { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 14px; color: var(--text-2); font-size: 12px; }.discovery-summary span { padding: 3px 7px; border: 1px solid var(--line); border-radius: 5px; }.desktop-section-actions,.desktop-path-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }.local-ai-row { display: flex; gap: 10px; align-items: center; font-size: 13px; }.local-ai-kinds { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }.desktop-settings-error { margin: 12px 0 0; color: var(--danger); font-size: 12px; }.desktop-settings-loading { min-height: 160px; display: grid; place-items: center; color: var(--text-3); }
</style>

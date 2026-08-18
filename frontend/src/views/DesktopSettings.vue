<template>
  <BuilderFrame :breadcrumbs="[{ label: '桌面设置' }]">
    <main class="desktop-settings-page">
      <div class="desktop-settings-content">
        <header class="desktop-settings-header">
          <div class="settings-title-mark"><AppIcon name="settings" :size="18" /></div>
          <div>
            <h1>桌面设置</h1>
            <p>管理远程服务、本机 AI 资源和桌面运行环境。</p>
          </div>
        </header>

        <div v-if="loading" class="desktop-settings-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>读取桌面配置</span>
        </div>
        <el-alert v-else-if="loadError" type="error" :closable="false" show-icon :title="loadError" />

        <div v-else class="desktop-settings-layout">
          <aside class="desktop-settings-sidebar" aria-label="桌面设置分类">
            <div class="settings-nav-label">连接与运行</div>
            <button
              v-for="item in primaryMenu"
              :key="item.id"
              type="button"
              class="desktop-settings-menu-item"
              :class="{ 'is-active': activeSection === item.id }"
              @click="activeSection = item.id"
            >
              <span class="menu-icon"><AppIcon :name="item.icon" :size="16" /></span>
              <span>{{ item.label }}</span>
            </button>

            <div class="settings-nav-label settings-nav-label-ai">本地 AI</div>
            <button
              v-for="item in localAiMenu"
              :key="item.id"
              type="button"
              class="desktop-settings-menu-item is-child"
              :class="{ 'is-active': activeSection === item.id }"
              @click="activeSection = item.id"
            >
              <span class="menu-icon"><AppIcon :name="item.icon" :size="15" /></span>
              <span>{{ item.label }}</span>
              <span class="menu-local-dot" aria-label="仅本机" />
            </button>

            <div class="settings-nav-label settings-nav-label-ai">共享配置</div>
            <button type="button" class="desktop-settings-menu-item" @click="openSharedConfiguration">
              <span class="menu-icon"><AppIcon name="settings" :size="16" /></span>
              <span>共享配置</span>
            </button>
          </aside>

          <section class="desktop-settings-panel">
            <header class="desktop-settings-panel-header">
              <div>
                <div class="panel-eyebrow">设置中心</div>
                <h2>{{ activeMeta.title }}</h2>
                <p>{{ activeMeta.description }}</p>
              </div>
              <el-button
                v-if="activeSection === 'environment'"
                plain
                :loading="environmentChecking"
                @click="refreshEnvironment"
              >
                <AppIcon name="refresh" :size="14" />
                重新检查
              </el-button>
            </header>

            <template v-if="activeSection === 'remote'">
              <div class="settings-card connection-card">
                <div class="card-heading">
                  <div class="card-heading-icon remote-icon"><AppIcon name="globe" :size="18" /></div>
                  <div><strong>远程服务</strong><span>认证、租户、应用和远程会话由这里决定。</span></div>
                  <el-tag v-if="discovery" type="success" effect="plain">已发现</el-tag>
                  <el-tag v-else type="info" effect="plain">未连接</el-tag>
                </div>
                <el-form label-position="top" class="desktop-field-form" @submit.prevent>
                  <el-form-item label="服务地址" :error="urlTouched ? urlError : ''">
                    <el-input
                      v-model="serviceUrl"
                      :disabled="saving || discovering"
                      placeholder="Control Plane 或 aPaaS Builder 地址"
                      @blur="urlTouched = true"
                    />
                    <DesktopServiceExamples />
                  </el-form-item>
                </el-form>
                <div v-if="discovery" class="discovery-summary">
                  <span class="summary-main"><AppIcon name="check" :size="13" /> {{ discovery.platform.name }}</span>
                  <span>{{ discovery.platform.type === 'apaas_builder' ? 'aPaaS Builder' : 'Control Plane' }}</span>
                  <span>{{ discovery.auth.provider === 'apaas' ? 'aPaaS 认证' : '平台认证' }}</span>
                  <span>Builder {{ discovery.products.builder.enabled ? '已启用' : '未启用' }}</span>
                  <span>Code {{ discovery.products.code.enabled ? '已启用' : '未启用' }}</span>
                </div>
                <p v-if="operationError" class="desktop-settings-error">{{ operationError }}</p>
                <div class="desktop-section-actions">
                  <el-button :loading="discovering" :disabled="saving || Boolean(urlError)" @click="rediscover">重新发现</el-button>
                  <el-button type="primary" :loading="saving" :disabled="!discovery || Boolean(urlError)" @click="saveConnection">保存并重新连接</el-button>
                </div>
              </div>
            </template>

            <template v-else-if="activeSection === 'local-model'">
              <div class="local-ai-banner">
                <div class="local-ai-banner-icon"><AppIcon name="laptop" :size="18" /></div>
                <div><strong>本机资源</strong><span>只在这台桌面客户端和本地工程中使用，不会覆盖远程配置。</span></div>
                <el-switch v-model="localAiEnabled" :disabled="saving" />
              </div>
              <LocalModelSettings v-if="localAiEnabled" />
              <div v-else class="settings-card resource-card"><div class="resource-empty"><div class="resource-empty-icon"><AppIcon name="bot" :size="24" /></div><strong>本机配置已关闭</strong><p>打开上方开关后即可维护本地模型。</p></div></div>
            </template>

            <template v-else-if="activeLocalAiKind">
              <div class="local-ai-banner">
                <div class="local-ai-banner-icon"><AppIcon name="laptop" :size="18" /></div>
                <div><strong>本机资源</strong><span>只在这台桌面客户端和本地工程中使用，不会覆盖远程配置。</span></div>
                <el-switch v-model="localAiEnabled" :disabled="saving" />
              </div>
              <div class="settings-card resource-card"><div class="resource-empty"><div class="resource-empty-icon"><AppIcon :name="activeMeta.icon" :size="24" /></div><strong>{{ localAiEnabled ? '本机配置已启用' : '本机配置已关闭' }}</strong><p>{{ localAiEnabled ? '该资源会与 Builder、Code 共用，后续可在这里维护。' : '打开上方开关后，本机工程才能使用这类资源。' }}</p></div></div>
            </template>

            <template v-else-if="activeSection === 'apaas'">
              <div class="settings-card">
                <div class="card-heading">
                  <div class="card-heading-icon app-icon-apaas"><AppIcon name="building" :size="18" /></div>
                  <div><strong>aPaaS 环境</strong><span>用于本地 Builder 的导入、发布和平台连接。</span></div>
                  <el-tag type="info" effect="plain">本地配置</el-tag>
                </div>
                <div class="info-row"><span>当前状态</span><strong>随远程服务发现</strong></div>
                <div class="info-row"><span>配置位置</span><strong>桌面客户端 SQLite</strong></div>
                <p class="desktop-settings-hint">这里不读取远程租户列表，避免把桌面本地配置误当成线上租户。</p>
              </div>
            </template>

            <template v-else-if="activeSection === 'environment'">
              <div class="settings-card">
                <div v-if="environmentError" class="environment-alert"><el-alert type="warning" :closable="false" show-icon :title="environmentError" /></div>
                <div class="environment-list">
                  <div class="environment-row">
                    <div class="environment-icon"><AppIcon name="monitor" :size="17" /></div>
                    <div class="environment-copy"><strong>桌面 Runtime</strong><span>{{ snapshot?.phase === 'ready' ? '本地 Runtime 与 sidecar 已启动' : '本地 Runtime 当前未就绪' }}</span></div>
                    <el-tag :type="snapshot?.phase === 'ready' ? 'success' : 'warning'" effect="plain">{{ snapshot?.phase === 'ready' ? '可用' : '需检查' }}</el-tag>
                  </div>
                  <div v-for="tool in environmentTools" :key="tool.name" class="environment-row">
                    <div class="environment-icon"><AppIcon name="terminal" :size="17" /></div>
                    <div class="environment-copy"><strong>{{ tool.name }}</strong><span>{{ tool.description }}</span></div>
                    <el-tag type="info" effect="plain">桌面检查</el-tag>
                  </div>
                </div>
                <p class="desktop-settings-hint">检查结果仅用于诊断，不会阻止客户端启动或自动安装工具。</p>
              </div>
            </template>

            <template v-else-if="activeSection === 'storage'">
              <div class="settings-card">
                <div class="card-heading">
                  <div class="card-heading-icon"><AppIcon name="database" :size="18" /></div>
                  <div><strong>本地存储</strong><span>桌面运行数据和日志都保存在本机。</span></div>
                </div>
                <el-form label-position="top" class="desktop-field-form storage-form" @submit.prevent>
                  <el-form-item label="本地根目录"><el-input :model-value="rootDir" readonly /></el-form-item>
                </el-form>
                <p v-if="operationError" class="desktop-settings-error">{{ operationError }}</p>
                <div class="desktop-path-actions">
                  <el-button :loading="openingPath === 'root'" @click="openPath('root')"><AppIcon name="folder" :size="15" />打开数据目录</el-button>
                  <el-button :loading="openingPath === 'logs'" @click="openPath('logs')"><AppIcon name="doc" :size="15" />打开日志目录</el-button>
                </div>
              </div>
            </template>

            <template v-else-if="activeSection === 'about'">
              <div class="settings-card about-card">
                <div class="card-heading">
                  <div class="card-heading-icon"><AppIcon name="help-circle" :size="18" /></div>
                  <div><strong>DolphinAI</strong><span>查看客户端版本、构建信息与更新状态。</span></div>
                </div>
                <div class="desktop-section-actions">
                  <el-button type="primary" @click="aboutDialogOpen = true">
                    查看版本与更新
                  </el-button>
                </div>
              </div>
            </template>
          </section>
        </div>
      </div>
    </main>
    <DesktopAboutDialog v-model="aboutDialogOpen" />
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import DesktopAboutDialog from '@/components/desktop/DesktopAboutDialog.vue'
import DesktopServiceExamples from '@/components/desktop/DesktopServiceExamples.vue'
import LocalModelSettings from '@/components/desktop/LocalModelSettings.vue'
import { useUserStore } from '@/stores/user'
import { openControlPlaneConsole } from '@/utils/controlPlaneConsole'
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

type SettingsSection = 'remote' | 'local-model' | 'local-skill' | 'local-mcp' | 'local-knowledge' | 'apaas' | 'environment' | 'storage' | 'about'
type LocalAIKind = 'model' | 'skill' | 'mcp' | 'knowledge'

const primaryMenu = [
  { id: 'remote' as const, label: '远程服务', icon: 'globe' },
  { id: 'apaas' as const, label: 'aPaaS 环境', icon: 'building' },
  { id: 'environment' as const, label: '环境检查', icon: 'terminal' },
  { id: 'storage' as const, label: '存储与诊断', icon: 'database' },
  { id: 'about' as const, label: '关于与更新', icon: 'help-circle' },
]
const localAiMenu = [
  { id: 'local-model' as const, label: '模型', icon: 'bot', kind: 'model' as LocalAIKind },
  { id: 'local-skill' as const, label: '技能', icon: 'sparkles', kind: 'skill' as LocalAIKind },
  { id: 'local-mcp' as const, label: 'MCP', icon: 'puzzle', kind: 'mcp' as LocalAIKind },
  { id: 'local-knowledge' as const, label: '知识库', icon: 'book-open', kind: 'knowledge' as LocalAIKind },
]
const sectionMeta: Record<SettingsSection, { title: string; description: string; icon: string; resourceTitle?: string; resourceHint?: string }> = {
  remote: { title: '远程服务', description: '连接 Control Plane 或仅 aPaaS Builder 服务，并重新发现平台能力。', icon: 'globe' },
  'local-model': { title: '本地模型', description: '维护 Builder 与 Code 共用的本机模型连接。', icon: 'bot', resourceTitle: '模型目录', resourceHint: '可供本机 Builder 和 Code 使用的模型。' },
  'local-skill': { title: '本地技能', description: '查看本机技能资源、版本和启停状态。', icon: 'sparkles', resourceTitle: '技能库', resourceHint: '仅本机工程可使用的技能资源。' },
  'local-mcp': { title: '本地 MCP', description: '查看本机 MCP Server 配置与可用状态。', icon: 'puzzle', resourceTitle: 'MCP Server', resourceHint: '连接本机工具和外部服务的能力。' },
  'local-knowledge': { title: '本地知识库', description: '查看仅供本机工程使用的知识资源。', icon: 'book-open', resourceTitle: '知识库', resourceHint: '本地文件和索引组成的知识资源。' },
  apaas: { title: 'aPaaS 环境', description: '维护本地 Builder 导入、发布所需的平台连接。', icon: 'building' },
  environment: { title: '环境检查', description: '检查桌面 Runtime 和常用开发工具，结果只用于诊断。', icon: 'terminal' },
  storage: { title: '存储与诊断', description: '查看桌面数据目录并打开本机日志。', icon: 'database' },
  about: { title: '关于与更新', description: '查看 DolphinAI 版本并手动检查客户端更新。', icon: 'help-circle' },
}

const activeSection = ref<SettingsSection>('remote')
const user = useUserStore()
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
const environmentChecking = ref(false)
const environmentError = ref('')
const aboutDialogOpen = ref(false)
const environmentTools = [
  { name: 'Git', description: '用于本地工程版本管理' },
  { name: 'Python', description: '用于本地工具和 Runtime 扩展' },
  { name: 'Node.js', description: '用于前端和脚本运行' },
]
const activeMeta = computed(() => sectionMeta[activeSection.value])
const activeLocalAiKind = computed(() => localAiMenu.find(item => item.id === activeSection.value)?.kind || null)
const urlError = computed(() => validateServiceUrl(serviceUrl.value))

function validateServiceUrl(value: string): string {
  try {
    const url = new URL(value.trim())
    return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password && !url.hash ? '' : '请输入有效的 HTTP(S) 地址'
  } catch { return '请输入有效的 HTTP(S) 地址' }
}

async function loadSettings() {
  loading.value = true
  loadError.value = ''
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

function openSharedConfiguration() {
  const config = snapshot.value?.config
  const baseUrl = config?.discovery_url || config?.discovery?.auth.login_url || config?.login.base_url || ''
  if (!baseUrl || config?.discovery?.auth.provider !== 'control_plane') {
    operationError.value = '请先连接 Control Plane，才能打开共享配置。'
    return
  }
  openControlPlaneConsole('/capabilities', {
    accessToken: user.token,
    tenantId: user.user?.control_plane_tenant_id,
  }, baseUrl)
}

async function saveConnection() {
  if (!discovery.value || urlError.value) return
  saving.value = true
  operationError.value = ''
  try {
    const mode = discovery.value.auth.provider === 'apaas' ? 'apaas' : 'control_plane'
    snapshot.value = await saveDesktopSetup(buildDesktopSetupInput(rootDir.value || snapshot.value?.default_root_dir || '', mode, discovery.value.auth.login_url, 'both', serviceUrl.value.trim(), discovery.value, localAiEnabled.value))
    if (__DESKTOP_WEB_PREVIEW__ || snapshot.value?.phase === 'ready' || snapshot.value?.phase === 'failed') {
      saving.value = false
    }
  } catch (error) {
    operationError.value = desktopErrorMessage(error, '保存连接失败')
    saving.value = false
  }
}

async function refreshEnvironment() {
  environmentChecking.value = true
  environmentError.value = ''
  try { environmentError.value = '桌面环境检查将在客户端桥接接入后显示实时结果。' }
  finally { environmentChecking.value = false }
}

async function openPath(kind: DesktopPathKind) {
  openingPath.value = kind
  operationError.value = ''
  try { await openDesktopPath(kind) } catch { operationError.value = '无法打开目录' }
  finally { openingPath.value = null }
}

onMounted(() => { void loadSettings() })
</script>

<style scoped>
.desktop-settings-page { flex: 1; min-height: 0; overflow-y: auto; padding: 30px 28px 48px; color: var(--text); background: var(--bg); }
.desktop-settings-content { width: min(1080px, 100%); margin: 0 auto; }
.desktop-settings-header { display: flex; align-items: flex-start; gap: 12px; }
.settings-title-mark { width: 34px; height: 34px; display: grid; place-items: center; color: var(--primary); border: 1px solid var(--line); border-radius: 9px; background: var(--surface); }
.desktop-settings-header h1 { margin: 0; font-size: 22px; line-height: 30px; letter-spacing: 0; }
.desktop-settings-header p { margin: 3px 0 0; color: var(--text-3); font-size: 12px; line-height: 18px; }
.desktop-settings-layout { display: grid; grid-template-columns: 204px minmax(0, 1fr); margin-top: 28px; min-height: 540px; }
.desktop-settings-sidebar { display: flex; flex-direction: column; gap: 4px; padding: 3px 22px 0 0; border-right: 1px solid var(--line); }
.settings-nav-label { padding: 8px 10px 5px; color: var(--text-3); font-size: 11px; font-weight: 700; letter-spacing: .04em; }
.settings-nav-label-ai { margin-top: 10px; }
.desktop-settings-menu-item { width: 100%; min-height: 38px; display: flex; align-items: center; gap: 9px; padding: 8px 10px; border: 0; border-radius: 7px; color: var(--text-2); background: transparent; font: inherit; font-size: 13px; line-height: 20px; text-align: left; cursor: pointer; transition: background .16s ease, color .16s ease; }
.desktop-settings-menu-item:hover { color: var(--text); background: var(--surface); }
.desktop-settings-menu-item.is-active { color: var(--primary); background: var(--primary-light); font-weight: 600; }
.desktop-settings-menu-item.is-child { padding-left: 20px; font-size: 12px; }
.menu-icon { width: 20px; display: inline-flex; justify-content: center; color: currentColor; }
.menu-local-dot { width: 5px; height: 5px; margin-left: auto; border-radius: 50%; background: #58a6ff; opacity: .8; }
.desktop-settings-panel { min-width: 0; padding: 2px 0 40px 34px; }
.desktop-settings-panel-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-bottom: 22px; border-bottom: 1px solid var(--line); }
.panel-eyebrow { margin-bottom: 5px; color: var(--text-3); font-size: 11px; letter-spacing: .06em; }
.desktop-settings-panel-header h2 { margin: 0; font-size: 18px; line-height: 26px; letter-spacing: 0; }
.desktop-settings-panel-header p { max-width: 600px; margin: 4px 0 0; color: var(--text-3); font-size: 12px; line-height: 18px; }
.settings-card { max-width: 700px; margin-top: 22px; padding: 20px 22px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); box-shadow: 0 8px 24px rgb(20 31 45 / 3%); }
.card-heading { display: flex; align-items: center; gap: 11px; min-height: 34px; }
.card-heading > div:nth-child(2) { min-width: 0; display: grid; gap: 3px; flex: 1; }
.card-heading strong { color: var(--text); font-size: 13px; }
.card-heading span { color: var(--text-3); font-size: 12px; line-height: 17px; }
.card-heading-icon { width: 34px; height: 34px; display: grid; place-items: center; flex-shrink: 0; color: var(--primary); border-radius: 8px; background: var(--primary-light); }
.remote-icon { color: #2878d4; background: #eaf3ff; }
.app-icon-apaas { color: #8a5a16; background: #fff4da; }
.desktop-field-form { width: min(620px, 100%); margin-top: 22px; }
.discovery-summary { display: flex; gap: 7px; flex-wrap: wrap; align-items: center; margin-top: 14px; color: var(--text-2); font-size: 12px; }
.discovery-summary span { padding: 4px 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); }
.discovery-summary .summary-main { display: inline-flex; align-items: center; gap: 4px; color: var(--success, #2e8b57); border-color: rgb(46 139 87 / 22%); background: rgb(46 139 87 / 7%); }
.desktop-section-actions, .desktop-path-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 18px; }
.desktop-section-actions :deep(.el-button), .desktop-path-actions :deep(.el-button), .desktop-settings-panel-header :deep(.el-button) { display: inline-flex; align-items: center; gap: 6px; }
.desktop-settings-error { margin: 12px 0 0; color: var(--danger); font-size: 12px; }
.desktop-settings-loading { min-height: 260px; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--text-3); font-size: 12px; }
.local-ai-banner { max-width: 700px; display: flex; align-items: center; gap: 11px; margin-top: 22px; padding: 13px 16px; border: 1px solid rgb(40 120 212 / 18%); border-radius: 9px; background: rgb(40 120 212 / 5%); }
.local-ai-banner-icon { width: 30px; height: 30px; display: grid; place-items: center; flex-shrink: 0; color: #2878d4; border-radius: 7px; background: #eaf3ff; }
.local-ai-banner > div:nth-child(2) { display: grid; gap: 2px; flex: 1; }
.local-ai-banner strong { font-size: 12px; }
.local-ai-banner span { color: var(--text-3); font-size: 11px; line-height: 17px; }
.resource-card { margin-top: 12px; }
.resource-empty { display: grid; justify-items: center; gap: 6px; padding: 44px 18px 30px; color: var(--text-2); text-align: center; }
.resource-empty-icon { width: 48px; height: 48px; display: grid; place-items: center; margin-bottom: 4px; color: var(--text-3); border-radius: 12px; background: var(--bg); }
.resource-empty strong { font-size: 13px; }
.resource-empty p { max-width: 400px; margin: 0; color: var(--text-3); font-size: 12px; line-height: 18px; }
.info-row { display: flex; justify-content: space-between; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--line); color: var(--text-3); font-size: 12px; }
.info-row strong { color: var(--text-2); font-weight: 500; }
.desktop-settings-hint { margin: 14px 0 0; color: var(--text-3); font-size: 12px; line-height: 18px; }
.environment-alert { margin: 18px 0 0; }
.environment-list { display: grid; margin-top: 8px; }
.environment-row { min-height: 66px; display: grid; grid-template-columns: 36px minmax(0, 1fr) auto; align-items: center; gap: 12px; border-bottom: 1px solid var(--line); }
.environment-icon { width: 32px; height: 32px; display: grid; place-items: center; color: var(--text-2); border-radius: 7px; background: var(--bg); }
.environment-copy { min-width: 0; display: grid; gap: 3px; }
.environment-copy strong { font-size: 13px; }
.environment-copy span { overflow: hidden; color: var(--text-3); font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.storage-form { margin-top: 20px; }
.desktop-settings-inline-hint { align-self: center; color: var(--text-3); font-size: 12px; }
@media (max-width: 760px) {
  .desktop-settings-page { padding: 22px 16px 36px; }
  .desktop-settings-layout { display: block; margin-top: 20px; }
  .desktop-settings-sidebar { flex-direction: row; gap: 4px; overflow-x: auto; padding: 0 0 12px; border-right: 0; border-bottom: 1px solid var(--line); }
  .settings-nav-label { display: none; }
  .desktop-settings-menu-item, .desktop-settings-menu-item.is-child { width: auto; min-width: max-content; padding: 8px 10px; }
  .desktop-settings-panel { padding: 22px 0 32px; }
  .settings-card { padding: 17px 16px; }
  .local-ai-banner { align-items: flex-start; }
  .environment-row { grid-template-columns: 36px minmax(0, 1fr); padding: 10px 0; }
  .environment-row :deep(.el-tag) { grid-column: 2; justify-self: start; }
}
</style>

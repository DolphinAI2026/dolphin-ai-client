<template>
  <WorkbenchShell>
    <main class="settings-page">
      <header class="settings-header">
              <div>
          <span class="settings-eyebrow">配置中心</span>
          <h1>设置</h1>
          <p>统一管理 AI 能力、系统账号、桌面运行参数和界面主题。</p>
        </div>
      </header>

      <div class="settings-layout">
        <aside class="settings-nav" aria-label="设置分类">
          <button
            v-for="item in sections"
            :key="item.key"
            type="button"
            class="settings-nav-item"
            :class="{ active: section === item.key }"
            @click="selectSection(item.key)"
          >
            <span class="settings-nav-icon"><AppIcon :name="item.icon" :size="16" /></span>
            <span>
              <strong>{{ item.label }}</strong>
              <small>{{ item.description }}</small>
            </span>
          </button>
        </aside>

        <section class="settings-content">
          <div class="settings-section-heading">
            <div>
              <span class="settings-section-kicker">{{ activeSection.label }}</span>
              <h2>{{ activeSection.title }}</h2>
            </div>
            <span v-if="visibleItems.length" class="settings-section-count">{{ visibleItems.length }} 项</span>
          </div>

          <div v-if="section !== 'theme'" class="settings-grid">
            <button
              v-for="item in visibleItems"
              :key="item.key"
              type="button"
              class="settings-card"
              :class="{ disabled: item.disabled }"
              :disabled="item.disabled"
              @click="openItem(item)"
            >
              <span class="settings-card-icon" :class="`tone-${item.tone}`">
                <AppIcon :name="item.icon" :size="18" />
              </span>
              <span class="settings-card-copy">
                <strong>{{ item.label }}</strong>
                <span>{{ item.description }}</span>
                <small v-if="item.status" :class="`status-${item.statusTone || 'muted'}`">{{ item.status }}</small>
              </span>
              <AppIcon v-if="!item.disabled" name="arrow-right" :size="16" class="settings-card-arrow" />
              <span v-else class="settings-card-soon">待接入</span>
            </button>
          </div>

          <div v-if="section === 'theme'" class="theme-panel">
            <div class="theme-panel-copy">
              <span class="settings-section-kicker">界面偏好</span>
              <h3>选择主题</h3>
              <p>主题设置会保存在当前账号的浏览器或桌面客户端中。</p>
            </div>
            <div class="theme-segmented" role="group" aria-label="主题模式">
              <button type="button" :class="{ active: theme.mode === 'light' }" @click="theme.setTheme('light')">
                <AppIcon name="palette" :size="16" />浅色
              </button>
              <button type="button" :class="{ active: theme.mode === 'dark' }" @click="theme.setTheme('dark')">
                <AppIcon name="palette" :size="16" />深色
              </button>
            </div>
          </div>

          <div v-if="section === 'desktop' && isDesktop" class="settings-inline-row">
            <div>
              <strong>客户端版本</strong>
              <span>检查并安装桌面端可用更新。</span>
            </div>
            <button type="button" class="settings-inline-action" @click="checkAndPromptUpdate({ silentIfNone: false })">
              <AppIcon name="refresh" :size="15" />
              检查更新
            </button>
          </div>

          <p v-if="section === 'desktop' && !isDesktop" class="settings-note">
            桌面端配置只在桌面客户端生效，Web 端不会修改本机运行参数。
          </p>
        </section>
      </div>
    </main>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/common/AppIcon.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { useThemeStore } from '@/stores/theme'
import { useUserStore } from '@/stores/user'
import { checkAndPromptUpdate, getCachedDesktopState, getDesktopState, isDesktop as desktopRuntime } from '@/utils/desktop'
import { openControlPlaneConsole } from '@/utils/controlPlaneConsole'

type SectionKey = 'ai' | 'system' | 'desktop' | 'theme'
type Tone = 'blue' | 'green' | 'orange' | 'purple' | 'slate'

interface SettingItem {
  key: string
  label: string
  description: string
  icon: string
  tone: Tone
  path?: string
  externalPath?: string
  status?: string
  statusTone?: 'ok' | 'muted' | 'warn'
  disabled?: boolean
  visible?: () => boolean
}

interface SettingSection {
  key: SectionKey
  label: string
  title: string
  description: string
  icon: string
  items: SettingItem[]
}

const route = useRoute()
const router = useRouter()
const theme = useThemeStore()
const user = useUserStore()
const isDesktop = __DESKTOP__
const isControlPlaneAccount = computed(() => (
  String(user.user?.account_source || '').toLowerCase() === 'control_plane'
  || Boolean(user.user?.control_plane_tenant_id)
))

const sections = computed<SettingSection[]>(() => [
  {
    key: 'ai',
    label: 'AI 配置',
    title: 'AI 配置',
    description: '模型、技能和 AI 工具等个人能力偏好。',
    icon: 'sparkles',
    items: [
      { key: 'models', label: '模型配置', description: '在 Control Plane 管理当前组织可用模型和默认模型。', icon: 'sparkles', tone: 'blue', externalPath: '/ai-models', visible: () => isDesktop || user.isTenantAdmin, status: '打开 Control Plane', statusTone: 'muted' },
      { key: 'skills', label: '技能', description: '在 Control Plane 管理共享技能和授权范围。', icon: 'wand', tone: 'purple', externalPath: '/skill-assets', status: '打开 Control Plane', statusTone: 'muted' },
      { key: 'mcp', label: 'MCP 工具', description: '在 Control Plane 管理共享 MCP 服务。', icon: 'tool', tone: 'green', externalPath: '/mcp-services', visible: () => user.isPlatformAdmin || isDesktop, status: '打开 Control Plane', statusTone: 'muted' },
      { key: 'knowledge', label: '知识库', description: '在 Control Plane 管理共享知识库和授权。', icon: 'book', tone: 'orange', externalPath: '/knowledge-bases', visible: () => user.isPlatformAdmin || isDesktop, status: '打开 Control Plane', statusTone: 'muted' },
      { key: 'local-models', label: '本地模型补充', description: '仅桌面端本地工程使用的 SQLite 模型，不会写入远程组织。', icon: 'cpu', tone: 'slate', path: '/platform-envs?tab=llm&source=local', visible: () => isDesktop, status: '仅本机可用', statusTone: 'muted' },
    ],
  },
  {
    key: 'theme',
    label: '主题',
    title: '主题',
    description: '调整界面显示模式和阅读体验。',
    icon: 'palette',
    items: [],
  },
  {
    key: 'system',
    label: '系统配置',
    title: '系统配置',
    description: '面向当前组织或部署环境的外部账号和凭据。',
    icon: 'settings',
    items: [
      { key: 'apaas', label: 'aPaaS 租户与账号', description: '在 Control Plane 管理组织的 aPaaS 接入。', icon: 'building', tone: 'blue', externalPath: '/apaas-access', visible: () => isDesktop || user.isTenantAdmin, status: '打开 Control Plane', statusTone: 'muted' },
      { key: 'git', label: 'Git 平台连接', description: '配置当前组织的默认 GitLab / GitHub 连接，供系统助手创建和推送系统资产仓库。', icon: 'link', tone: 'orange', path: '/settings/git', visible: () => user.isTenantAdmin, status: '租户级默认连接', statusTone: 'muted' },
      { key: 'k8s', label: '运行环境', description: '在 Control Plane 管理远程运行环境和发布凭据。', icon: 'database', tone: 'green', externalPath: '/environments', status: '打开 Control Plane', statusTone: 'muted' },
      { key: 'members', label: '组织账号与成员', description: '在 Control Plane 管理组织成员和权限。', icon: 'users', tone: 'slate', externalPath: '/admin-users', visible: () => user.isTenantAdmin || isDesktop, status: '打开 Control Plane', statusTone: 'muted' },
    ],
  },
  {
    key: 'desktop',
    label: '桌面端配置',
    title: '桌面端配置',
    description: '只影响本机客户端的登录、入口和本地目录。',
    icon: 'monitor',
    items: [
      { key: 'desktop-runtime', label: '桌面运行设置', description: '登录服务、工作台入口、本地根目录和日志目录。', icon: 'monitor', tone: 'slate', path: '/desktop-settings' },
    ],
  },
])

const section = computed<SectionKey>(() => {
  const raw = Array.isArray(route.query.section) ? route.query.section[0] : route.query.section
  const tab = Array.isArray(route.query.tab) ? route.query.tab[0] : route.query.tab
  if (raw === 'personal' || tab === 'llm' || tab === 'assistant') return 'ai'
  if (tab === 'envs') return 'system'
  return raw === 'system' || raw === 'desktop' || raw === 'theme' ? raw : 'ai'
})

const activeSection = computed(() => sections.value.find(item => item.key === section.value) || sections.value[0])
const visibleItems = computed(() => activeSection.value.items.filter(item => item.visible?.() ?? true))

function selectSection(next: SectionKey) {
  router.replace({ path: '/settings', query: { ...route.query, section: next } })
}

function openItem(item: SettingItem) {
  if (item.externalPath) {
    void openRemoteItem(item.externalPath)
    return
  }
  if (item.path) router.push(item.path)
}

async function openRemoteItem(path: string) {
  let config = getCachedDesktopState()?.config
  if (!config && desktopRuntime) {
    try { config = (await getDesktopState()).config } catch { /* keep the settings page usable */ }
  }
  const baseUrl = config?.discovery_url || config?.discovery?.auth.login_url || config?.login.base_url || ''
  if (isDesktop && (!isControlPlaneAccount.value || config?.discovery?.auth.provider !== 'control_plane')) {
    router.push('/desktop-settings')
    return
  }
  if (isDesktop && !baseUrl) {
    router.push('/desktop-settings')
    return
  }
  openControlPlaneConsole(path, {
    accessToken: user.token,
    tenantId: user.user?.control_plane_tenant_id,
  }, baseUrl)
}
</script>

<style scoped>
.settings-page {
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding: 34px clamp(20px, 4vw, 56px) 56px;
  background: var(--bg, #f8fafc);
  color: var(--text);
}
.settings-header,
.settings-layout {
  width: min(1120px, 100%);
  margin: 0 auto;
}
.settings-header { margin-bottom: 28px; }
.settings-eyebrow,
.settings-section-kicker {
  color: var(--brand);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.settings-header h1 { margin: 5px 0 6px; font-size: 28px; line-height: 1.2; }
.settings-header p { margin: 0; color: var(--text-3); font-size: 13px; }
.settings-layout { display: grid; grid-template-columns: 232px minmax(0, 1fr); gap: 32px; align-items: start; }
.settings-nav { display: grid; gap: 8px; position: sticky; top: 0; }
.settings-nav-item {
  display: flex; gap: 10px; align-items: flex-start; min-height: 64px; width: 100%; padding: 12px; text-align: left;
  border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--text-2); cursor: pointer;
}
.settings-nav-item:hover { background: var(--surface); border-color: var(--line); }
.settings-nav-item.active { background: var(--brand-soft); border-color: var(--brand-ring); color: var(--brand); }
.settings-nav-icon { display: grid; place-items: center; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 7px; background: var(--surface); }
.settings-nav-item strong, .settings-nav-item small { display: block; }
.settings-nav-item strong { font-size: 13px; line-height: 18px; }
.settings-nav-item small { margin-top: 2px; color: var(--text-3); font-size: 11px; line-height: 16px; }
.settings-section-heading { display: flex; justify-content: space-between; align-items: end; margin-bottom: 14px; }
.settings-section-heading h2 { margin: 4px 0 0; font-size: 20px; }
.settings-section-count { color: var(--text-3); font-size: 12px; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.settings-card {
  min-height: 120px; display: flex; align-items: flex-start; gap: 12px; position: relative; padding: 16px;
  border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); text-align: left; cursor: pointer;
  transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease;
}
.settings-card:hover { border-color: var(--brand-ring); box-shadow: 0 8px 24px rgba(15, 23, 42, .08); transform: translateY(-1px); }
.settings-card.disabled { cursor: default; opacity: .62; }
.settings-card-icon { display: grid; place-items: center; width: 34px; height: 34px; flex: 0 0 34px; border-radius: 8px; }
.tone-blue { color: #2563eb; background: #eff6ff; } .tone-green { color: #059669; background: #ecfdf5; }
.tone-orange { color: #d97706; background: #fffbeb; } .tone-purple { color: #7c3aed; background: #f5f3ff; }
.tone-slate { color: #475569; background: #f1f5f9; }
.settings-card-copy { min-width: 0; padding-right: 16px; }
.settings-card-copy strong, .settings-card-copy span, .settings-card-copy small { display: block; }
.settings-card-copy strong { font-size: 14px; line-height: 20px; }
.settings-card-copy span { margin-top: 5px; color: var(--text-3); font-size: 12px; line-height: 18px; }
.settings-card-copy small { margin-top: 8px; font-size: 11px; }
.status-ok { color: var(--ok); } .status-warn { color: var(--warn); } .status-muted { color: var(--text-4); }
.settings-card-arrow { position: absolute; top: 17px; right: 14px; color: var(--text-4); }
.settings-card-soon { margin-left: auto; color: var(--text-4); font-size: 11px; white-space: nowrap; }
.settings-note { margin: 18px 0 0; color: var(--text-3); font-size: 12px; }
.settings-inline-row {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  margin-top: 16px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface);
}
.settings-inline-row strong, .settings-inline-row span { display: block; }
.settings-inline-row strong { font-size: 13px; line-height: 18px; }
.settings-inline-row span { margin-top: 3px; color: var(--text-3); font-size: 12px; line-height: 17px; }
.settings-inline-action {
  display: inline-flex; align-items: center; gap: 7px; flex: 0 0 auto; padding: 8px 11px;
  border: 1px solid var(--line); border-radius: 7px; background: var(--surface-2); color: var(--text-2); cursor: pointer;
}
.settings-inline-action:hover { border-color: var(--brand-ring); color: var(--brand); }
.settings-grid-extra { margin-top: 12px; }
.theme-panel {
  display: flex; align-items: center; justify-content: space-between; gap: 24px;
  min-height: 168px; padding: 24px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface);
}
.theme-panel-copy h3 { margin: 5px 0 5px; font-size: 20px; }
.theme-panel-copy p { margin: 0; color: var(--text-3); font-size: 13px; }
.theme-segmented { display: inline-flex; gap: 4px; padding: 4px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-2); }
.theme-segmented button { display: inline-flex; align-items: center; gap: 7px; padding: 9px 13px; border: 0; border-radius: 6px; background: transparent; color: var(--text-2); cursor: pointer; }
.theme-segmented button.active { background: var(--surface); color: var(--brand); box-shadow: 0 1px 3px rgba(15, 23, 42, .1); }
@media (max-width: 760px) {
  .settings-layout { grid-template-columns: 1fr; gap: 20px; }
  .settings-nav { position: static; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .settings-nav-item { padding: 10px; }
  .settings-nav-item small { display: none; }
}
@media (max-width: 520px) {
  .settings-grid { grid-template-columns: 1fr; }
  .settings-nav { grid-template-columns: 1fr; }
  .theme-panel { align-items: flex-start; flex-direction: column; }
}
</style>

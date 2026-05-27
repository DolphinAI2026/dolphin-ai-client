<!--
  ApaasEmbedIframe.vue — 通用 apaas 平台 iframe wrapper (design-v4 SPEC 落地).

  2026-05-27 R: 业务视角 + 对话 = 我们做; 手动改字段 / 流程 / 数据 / 权限 = iframe
  apaas 原生页面. 4 个 panel (Form/List/Data/Process/Permission) edit mode 全用这个
  组件 mount apaas 真编辑器 (走 platform-proxy SSO 注入 token).

  Props:
    - appId       (number, required) — ai-builder 应用 id
    - menuId      (string?)            — apaas menu_id (form_id 关联的菜单)
    - formId      (string|null?)       — apaas form_id (跟 menuId 配套)
    - menuType    (string?)            — MODEL / QUOTE / 等 — 决定 editor 子路径
    - mode        ('config'|'runtime') — 默 'config' (编辑器). 'runtime' 走真应用页 (CUSTOM 首页用)

  URL: buildPlatformProxyMenuUrl(appId, token, {menuId, formId, menuType}) +
  mode='runtime' 时 append &redirect_kind=runtime (让 backend _build_menu_redirect_path
  返 app runtime URL 而不是 editor URL).

  expose: reload() — bump key 触发 iframe re-mount, 刷新 SSO + 重新加载页面.

  错误 fallback: iframe 加载失败 / 应用未部署 时显友好提示 + 重试 button.

  视觉: 跟 design-v3 token 一致 (--brand / --surface / --text-2 / --font-sans),
  iframe 占满父容器无 border.
-->
<template>
  <section class="aei" aria-label="apaas 平台原生编辑器">
    <div v-if="!appId" class="aei-empty">
      <div class="aei-empty-icon">🔌</div>
      <h3>未选应用</h3>
      <p>需要应用 ID 才能加载 apaas 原生编辑器.</p>
    </div>
    <div v-else-if="loadError" class="aei-error">
      <div class="aei-error-icon">⚠️</div>
      <h3>加载平台编辑器失败</h3>
      <p>{{ loadError }}</p>
      <button class="aei-btn" @click="reload">重试</button>
    </div>
    <template v-else>
      <iframe
        :key="iframeKey"
        ref="iframeRef"
        class="aei-iframe"
        :src="iframeUrl"
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals allow-downloads"
        allow="clipboard-read; clipboard-write"
        title="apaas 平台原生编辑器"
        @load="onIframeLoad"
        @error="onIframeError"
      />
      <div v-if="loading" class="aei-loading">
        <div class="aei-loading-spinner" />
        <span>正在加载 apaas 编辑器…</span>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useUserStore } from '@/stores/user'
import { buildPlatformProxyMenuUrl } from '@/utils/platformIframe'

const props = withDefaults(
  defineProps<{
    appId: number
    menuId?: string
    formId?: string | null
    menuType?: string
    mode?: 'config' | 'runtime'
    /** 2026-05-27 S: 决定 iframe 内打开哪个 sub-designer (form/list/process/page).
     *  form = 表单设计 (默认), list = 列表设计, process = 流程设计, page = 页面设置.
     *  当前 URL 里追加 &designer_sub=X 让 backend / apaas 知道 (P5: apaas 真支持后落地).
     */
    designerSub?: 'form' | 'list' | 'process' | 'page'
  }>(),
  {
    menuId: '',
    formId: null,
    menuType: '',
    mode: 'config',
    designerSub: 'form',
  },
)

const userStore = useUserStore()
const iframeKey = ref(0)
const iframeRef = ref<HTMLIFrameElement | null>(null)
const loading = ref(true)
const loadError = ref('')

const iframeUrl = computed(() => {
  const token = userStore.token || localStorage.getItem('token') || ''
  const base = buildPlatformProxyMenuUrl(props.appId, token, {
    menuId: props.menuId || undefined,
    formId: props.formId || undefined,
    menuType: props.menuType || undefined,
  })
  const params: string[] = []
  if (props.mode === 'runtime') params.push('redirect_kind=runtime')
  // 2026-05-27 S: 传 sub-designer 提示给 backend / apaas (P5: apaas 接通 designer_sub
  // query 落地后自动跳对应 tab; 当前 apaas 可能忽略, iframe 显默认表单设计).
  if (props.designerSub && props.designerSub !== 'form') params.push(`designer_sub=${props.designerSub}`)
  if (params.length === 0) return base
  const sep = base.includes('?') ? '&' : '?'
  return `${base}${sep}${params.join('&')}`
})

function reload() {
  loadError.value = ''
  loading.value = true
  iframeKey.value += 1
}

function onIframeLoad() {
  loading.value = false
  // 2026-05-27 S: 注入 CSS 隐藏 apaas form designer 内部顶栏 (← 图书管理 / Form Design
  // tabs / Save / Close) — 我们外层 mdsh-subnav 已有这些信息 + 操作, 内部 chrome 冗余.
  // best-effort: 找 common 选择器, 找不到默认 css 不生效, iframe 正常显.
  // P5: 实测 apaas DOM 类名 (用户报告才能精确), 当前用 broad pattern guess.
  try {
    const win = iframeRef.value?.contentWindow
    const doc = win?.document
    if (doc && !doc.querySelector('#aei-injected-style')) {
      const style = doc.createElement('style')
      style.id = 'aei-injected-style'
      style.textContent = `
        /* apaas 表单/列表设计器内部顶栏 — 我们外层已显这些 */
        .designer-header, .form-designer-header, .data-model-fn-config-header,
        .fn-config-header, .editor-top-bar, .designer-top-bar,
        .design-tabs, .designer-tabs, .editor-tabs,
        .app-fn-config-header, .form-editor-header,
        [class*="designerHeader"], [class*="DesignerHeader"] {
          display: none !important;
        }
      `
      ;(doc.head || doc.body).appendChild(style)
    }
  } catch {
    /* cross-origin / 时序问题忽略 — best effort */
  }
}

function onIframeError() {
  loading.value = false
  loadError.value = 'iframe 加载失败 — 检查网络或刷新页面'
}

// 切 menu / form / mode 时自动 re-mount, 强制 fresh load (避免 iframe 内部 SPA 缓存
// 老菜单的状态)
watch(
  () => [props.appId, props.menuId, props.formId, props.menuType, props.mode, props.designerSub],
  () => {
    reload()
  },
)

defineExpose({ reload })
</script>

<style scoped>
.aei {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface, #fff);
  font-family: var(--font-sans);
  color: var(--text);
  overflow: hidden;
}

.aei-iframe {
  flex: 1;
  width: 100%;
  height: 100%;
  border: 0;
  background: var(--surface, #fff);
  display: block;
}

.aei-empty,
.aei-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  padding: 48px 16px;
  gap: 12px;
  color: var(--text-3);
}
.aei-empty-icon,
.aei-error-icon {
  font-size: 40px;
  line-height: 1;
}
.aei-empty h3,
.aei-error h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.aei-empty p,
.aei-error p {
  margin: 0;
  font-size: 13px;
  color: var(--text-3);
}

.aei-btn {
  margin-top: 8px;
  padding: 6px 14px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  color: var(--surface, #fff);
  background: var(--brand);
  border: 0;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.aei-btn:hover {
  background: var(--brand-hover);
}

.aei-loading {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgba(248, 250, 252, 0.85);
  color: var(--text-2);
  font-size: 13px;
  font-family: var(--font-sans);
  pointer-events: none;
  z-index: 1;
}
.aei-loading-spinner {
  width: 22px;
  height: 22px;
  border: 2.5px solid var(--brand-soft-2, #dbeafe);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: aei-spin 0.85s linear infinite;
}
@keyframes aei-spin {
  to { transform: rotate(360deg); }
}
</style>

<template>
  <div class="extension-section">
    <header class="ext-header">
      <h3 class="ext-title">扩展开发</h3>
      <p class="ext-hint">
        为应用添加自定义组件 / 后端代码 / 平台扩展.
        操作会在<strong>新标签页</strong>打开, 当前对话不会丢上下文.
      </p>
    </header>

    <!-- 两张大卡片: 跳走入口 -->
    <div class="ext-cards">
      <button
        type="button"
        class="ext-card"
        :class="{ 'ext-card--disabled': !canOpenAiCoding }"
        @click="openAiCoding"
      >
        <div class="ext-card-icon" aria-hidden="true"><AppIcon name="laptop" :size="28" /></div>
        <h4 class="ext-card-title">二次开发自开发包</h4>
        <p class="ext-card-desc">
          对话式开发前端组件 / 后端服务.
          完成 publish 后自动通知本页面, 一键 republish 让组件生效.
        </p>
        <span class="ext-card-cta">→ 进入对话式开发</span>
      </button>

      <button
        type="button"
        class="ext-card"
        :class="{ 'ext-card--disabled': !platformDevKitUrl }"
        @click="openPlatformDevKit"
      >
        <div class="ext-card-icon" aria-hidden="true"><AppIcon name="package" :size="28" /></div>
        <h4 class="ext-card-title">平台自开发资源管理</h4>
        <p class="ext-card-desc">
          直接在 aPaaS 平台界面管理自开发资源 / 上传 zip / 关联应用.
        </p>
        <span class="ext-card-cta">→ 打开 (新标签)</span>
      </button>
    </div>

    <!-- 外部更新通知 banner (轮询 / SSE 收到时显) -->
    <el-alert
      v-if="externalUpdateAvailable"
      class="ext-alert"
      type="warning"
      :closable="false"
      show-icon
    >
      <template #title>
        <span>{{ externalUpdateMessage }}</span>
      </template>
      <template #default>
        <div class="ext-alert-actions">
          <el-button
            type="primary"
            size="small"
            :loading="republishing"
            @click="republishApp"
          >立即重发</el-button>
          <el-button size="small" @click="dismissUpdate">稍后</el-button>
          <el-button size="small" text @click="refreshDevKits">刷新列表</el-button>
        </div>
      </template>
    </el-alert>

    <!-- 当前应用已 attach 的自开发资源 -->
    <section class="ext-dev-kits">
      <div class="ext-dev-kits-head">
        <h4>当前应用已关联的扩展资源</h4>
        <span class="ext-badge">{{ devKits.length }}</span>
        <span class="ext-spacer" />
        <button
          type="button"
          class="ext-link-btn"
          :disabled="loading"
          @click="refreshDevKits"
        >{{ loading ? '加载中…' : '刷新' }}</button>
      </div>

      <ul v-if="devKits.length" class="ext-dev-kit-list">
        <li v-for="kit in devKits" :key="kit.id" class="ext-dev-kit-item">
          <span class="ext-dev-kit-name">{{ kit.fileName || '(未命名)' }}</span>
          <span v-if="kit.fileType" class="ext-dev-kit-type">{{ kit.fileType }}</span>
          <span v-if="kit.userName" class="ext-dev-kit-by">由 {{ kit.userName }}</span>
          <span v-if="kit.createTime" class="ext-dev-kit-time">{{ kit.createTime }}</span>
        </li>
      </ul>

      <div v-else-if="!loading && !errorNote" class="ext-empty">
        暂无关联的自开发包 — 用上方"二次开发自开发包"卡片创建一个.
      </div>

      <div v-if="errorNote" class="ext-error-note">
        {{ errorNote }}
      </div>
    </section>

    <!-- 连接状态指示 (开发友好, 生产可隐) -->
    <footer v-if="showDebug" class="ext-debug">
      <span>SSE: <code>{{ sseStatus }}</code></span>
      <span>轮询: 每 {{ pollIntervalMs / 1000 }}s</span>
      <span>上次轮询: <code>{{ lastPollAt || '—' }}</code></span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElAlert, ElButton, ElMessage } from 'element-plus'
import AppIcon from '@/components/common/AppIcon.vue'
import extensionApi, { type DevKitItem, type ExtensionUpdateEvent } from '@/api/extension'

const props = withDefaults(defineProps<{
  appId: number
  apaasAppId: string
  envId: number
  /** 平台自开发资源管理 URL — 不传则按当前 trial / 默认推断 */
  platformDevKitUrl?: string
  /** 轮询频率, 默认 30s */
  pollIntervalMs?: number
  /** 显示连接状态 footer (生产环境可关掉) */
  showDebug?: boolean
}>(), {
  platformDevKitUrl: '',
  pollIntervalMs: 30000,
  showDebug: false,
})

const emit = defineEmits<{
  (e: 'navigated', target: 'ai-coding' | 'platform-dev-kit'): void
  (e: 'external-update', payload: ExtensionUpdateEvent): void
  (e: 'republished', version: string): void
}>()

const router = useRouter()

// ─────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────
const devKits = ref<DevKitItem[]>([])
const loading = ref(false)
const errorNote = ref('')
const externalUpdateAvailable = ref(false)
const externalUpdateMessage = ref('检测到自开发资源已更新, 是否重新发布应用让变更生效?')
const republishing = ref(false)
const lastSeenKitIds = ref<Set<string>>(new Set())
const lastPollAt = ref('')
const sseStatus = ref<'idle' | 'connecting' | 'open' | 'error' | 'closed'>('idle')

let pollTimer: ReturnType<typeof setInterval> | null = null
// 2026-05-26 (PR6 reviewer Critical #2): SSE 现在走 controlled handle (.close() +
// 内部自管退避), 不再裸 EventSource. handle 是 { close: () => void }.
let eventSource: { close: () => void } | null = null

// ─────────────────────────────────────────────────────
// Computed
// ─────────────────────────────────────────────────────
const canOpenAiCoding = computed(() => Boolean(props.appId))
const platformDevKitUrl = computed(() => {
  if (props.platformDevKitUrl) return props.platformDevKitUrl
  // 占位推断 — 真实链路应由 PR2b 注入或 platform_proxy 返
  // 留空时按钮 disabled
  return ''
})

// ─────────────────────────────────────────────────────
// 二次开发入口 — 结构化交接到 AI Builder（AIChatPage）在应用上下文里做开发.
// 同标签进 /ai-chat?app_dev=1, 不再开新标签到独立 /coding.
// ─────────────────────────────────────────────────────
function openAiCoding() {
  if (!canOpenAiCoding.value) return
  const message =
    `我要为应用（app_id=${props.appId}）开发自开发包(组件 / 页面 / 接口)。`
    + `请先读这个应用的结构,再问我具体要开发什么。`
  sessionStorage.setItem(
    'ai_builder_pending_app_dev',
    JSON.stringify({
      message,
      app_id: props.appId,
      app_name: '',
      from: 'extension',
    }),
  )
  router.push({ path: '/ai-chat', query: { app_dev: '1' } })
  emit('navigated', 'ai-coding')
}

function openPlatformDevKit() {
  const url = platformDevKitUrl.value
  if (!url) {
    ElMessage.warning('平台自开发资源管理 URL 未配置 — 在 ChatPage 接入时由 platform_proxy 注入')
    return
  }
  window.open(url, '_blank', 'noopener')
  emit('navigated', 'platform-dev-kit')
}

// ─────────────────────────────────────────────────────
// 数据获取
// ─────────────────────────────────────────────────────
async function refreshDevKits() {
  if (!props.appId) return
  loading.value = true
  errorNote.value = ''
  try {
    const resp = await extensionApi.listDevKits(props.appId)
    lastPollAt.value = new Date().toLocaleTimeString()
    const newKits = resp.kits || []

    // 比对上次结果 — 有新 id 出现说明有外部更新
    const prevIds = lastSeenKitIds.value
    const currentIds = new Set(newKits.map(k => k.id))
    const isFirstLoad = prevIds.size === 0 && devKits.value.length === 0

    devKits.value = newKits
    if (!isFirstLoad) {
      const newOnes = newKits.filter(k => !prevIds.has(k.id))
      if (newOnes.length > 0) {
        externalUpdateMessage.value = `检测到 ${newOnes.length} 个新自开发包: ${newOnes.slice(0, 2).map(k => k.fileName).join(', ')}${newOnes.length > 2 ? ' …' : ''}, 是否重新发布应用?`
        externalUpdateAvailable.value = true
      }
    }
    lastSeenKitIds.value = currentIds

    if (resp.note) {
      errorNote.value = resp.note
    }
  } catch (err: any) {
    errorNote.value = `获取自开发包失败: ${err?.message || err}`
  } finally {
    loading.value = false
  }
}

async function republishApp() {
  if (!props.appId || republishing.value) return
  republishing.value = true
  try {
    const resp = await extensionApi.republishApplication(props.appId)
    if (resp.ok) {
      ElMessage.success(`重发成功 (版本 ${resp.version || '—'})`)
      externalUpdateAvailable.value = false
      emit('republished', resp.version || '')
    } else {
      ElMessage.error(resp.note || '重发失败')
    }
  } catch (err: any) {
    ElMessage.error(`重发失败: ${err?.message || err}`)
  } finally {
    republishing.value = false
  }
}

function dismissUpdate() {
  externalUpdateAvailable.value = false
}

// ─────────────────────────────────────────────────────
// SSE 订阅 — 当外部 (ai-coding agent) publish 完成时实时推送
// ─────────────────────────────────────────────────────
function openSse() {
  if (!props.appId) return
  closeSse()
  sseStatus.value = 'connecting'
  try {
    eventSource = extensionApi.openUpdateEventStream(props.appId, {
      onOpen: () => {
        sseStatus.value = 'open'
      },
      onEvent: (e: ExtensionUpdateEvent) => {
        if (e.type === 'hello' || e.type === 'ping') return
        if (e.type === 'dev_kit_published' || e.type === 'dev_kit_attached') {
          const kitName = (e as any).kit_name || (e as any).kit_id || '新自开发包'
          externalUpdateMessage.value = `${kitName} 已发布, 是否重新发布应用让变更生效?`
          externalUpdateAvailable.value = true
          // 触发一次刷新拿最新列表
          refreshDevKits()
        } else if (e.type === 'republish_done') {
          externalUpdateAvailable.value = false
          ElMessage.info(`应用已重发 (版本 ${(e as any).version || '—'})`)
        }
        emit('external-update', e)
      },
      onError: () => {
        sseStatus.value = 'error'
        // PR6 Critical: handle 内部用指数退避自管重连, 不再裸 EventSource 风暴.
      },
    })
  } catch (err) {
    sseStatus.value = 'error'
    console.warn('[ExtensionSectionPanel] SSE init failed:', err)
  }
}

function closeSse() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
    sseStatus.value = 'closed'
  }
}

// ─────────────────────────────────────────────────────
// 轮询 (SSE fallback / 兜底)
// ─────────────────────────────────────────────────────
function startPolling() {
  stopPolling()
  if (props.pollIntervalMs > 0) {
    pollTimer = setInterval(refreshDevKits, props.pollIntervalMs)
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ─────────────────────────────────────────────────────
// Lifecycle
// ─────────────────────────────────────────────────────
onMounted(() => {
  refreshDevKits()
  openSse()
  startPolling()
})

onBeforeUnmount(() => {
  closeSse()
  stopPolling()
})

watch(() => props.appId, (next, prev) => {
  if (next !== prev) {
    lastSeenKitIds.value = new Set()
    devKits.value = []
    externalUpdateAvailable.value = false
    refreshDevKits()
    openSse()
  }
})
</script>

<style scoped>
.extension-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
  background: var(--t-bg-base, #f8fafc);
  color: var(--t-text-primary, #1e293b);
  border-radius: 12px;
}

.ext-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ext-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--t-text-primary, #1e293b);
}
.ext-hint {
  margin: 0;
  font-size: 13px;
  color: var(--t-text-secondary, #64748b);
  line-height: 1.5;
}
.ext-hint strong {
  color: var(--t-brand-text, #4f6ef7);
  font-weight: 600;
}

/* 两大跳走卡片 */
.ext-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.ext-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 20px;
  background: var(--t-bg-panel, #ffffff);
  border: 1px solid var(--t-border-strong, rgba(99, 102, 241, 0.15));
  border-radius: 12px;
  cursor: pointer;
  text-align: left;
  color: inherit;
  font: inherit;
  transition: all 0.2s ease;
  box-shadow: var(--t-shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.04));
}
.ext-card:hover:not(.ext-card--disabled) {
  border-color: var(--t-brand-text, #4f6ef7);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px var(--t-brand-glow, rgba(79, 110, 247, 0.18));
}
.ext-card:focus-visible {
  outline: 2px solid var(--t-brand-text, #4f6ef7);
  outline-offset: 2px;
}
.ext-card--disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.ext-card-icon {
  font-size: 28px;
  line-height: 1;
}
.ext-card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--t-text-primary, #1e293b);
}
.ext-card-desc {
  margin: 0;
  font-size: 12px;
  color: var(--t-text-secondary, #64748b);
  line-height: 1.5;
}
.ext-card-cta {
  margin-top: auto;
  padding-top: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--t-brand-text, #4f6ef7);
}

/* 更新 banner */
.ext-alert {
  margin: 0;
}
.ext-alert-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}

/* dev kit 列表 */
.ext-dev-kits {
  background: var(--t-bg-panel, #ffffff);
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ext-dev-kits-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ext-dev-kits-head h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--t-text-primary, #1e293b);
}
.ext-badge {
  font-size: 11px;
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.08));
  color: var(--t-brand-text, #4f6ef7);
  border-radius: 10px;
  padding: 2px 8px;
  line-height: 1.4;
}
.ext-spacer { flex: 1; }
.ext-link-btn {
  background: transparent;
  border: none;
  font-size: 12px;
  color: var(--t-brand-text, #4f6ef7);
  cursor: pointer;
  padding: 4px 6px;
}
.ext-link-btn:hover:not(:disabled) { text-decoration: underline; }
.ext-link-btn:disabled { color: var(--t-text-muted, #94a3b8); cursor: default; }

.ext-dev-kit-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ext-dev-kit-item {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  padding: 8px 10px;
  background: var(--t-bg-base, #f8fafc);
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  border-radius: 6px;
  font-size: 13px;
}
.ext-dev-kit-name {
  font-weight: 500;
  color: var(--t-text-primary, #1e293b);
}
.ext-dev-kit-type {
  font-size: 11px;
  color: var(--t-text-secondary, #64748b);
  background: var(--t-bg-panel, #ffffff);
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  border-radius: 4px;
  padding: 1px 6px;
}
.ext-dev-kit-by,
.ext-dev-kit-time {
  font-size: 11px;
  color: var(--t-text-muted, #94a3b8);
}
.ext-empty {
  font-size: 13px;
  color: var(--t-text-muted, #94a3b8);
  padding: 8px 0;
}
.ext-error-note {
  font-size: 12px;
  color: var(--t-text-secondary, #64748b);
  padding: 6px 10px;
  background: var(--t-bg-base, #f8fafc);
  border-radius: 6px;
}

.ext-debug {
  display: flex;
  gap: 14px;
  font-size: 11px;
  color: var(--t-text-muted, #94a3b8);
  padding-top: 4px;
  border-top: 1px dashed var(--t-border-subtle, rgba(99, 102, 241, 0.08));
}
.ext-debug code {
  background: var(--t-bg-code, #f5f7fc);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 11px;
}
</style>

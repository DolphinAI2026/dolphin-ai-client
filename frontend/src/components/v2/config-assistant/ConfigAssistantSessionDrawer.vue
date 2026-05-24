<!-- frontend/src/components/v2/config-assistant/ConfigAssistantSessionDrawer.vue
     2026-05-24 ConfigAssistantPanel 加 "新对话" / "历史" 抽屉 — 学 super-agents-dev
     session-history-drawer.vue 模式, 但用项目自带 CSS tokens (不引 element-plus
     drawer, 保持 v2 design system 一致 dark / light 自适应).

     抽屉位置：从主面板左侧滑出 + overlay 半透明背景. 主容器 ConfigAssistantPanel
     传 :open / @update:open 控制显隐.

     props:
       applicationId       — 当前应用 id (拉 sessions 时按这个过滤)
       currentSessionId    — 高亮当前选中那条
       open                — v-model:open 双向绑定显隐

     emit:
       select(sid)         — 用户点某条 session card
       new                 — 用户点 "+ 新对话"
       delete(sid)         — 用户确认删除 (caller 决定是否要弹 confirm)
       rename(sid, title)  — 用户改了 title (内部 prompt 拿到新值, 直接抛给 caller)
       update:open(val)    — 抽屉外侧点击 overlay / Esc 关闭

     主容器 ConfigAssistantPanel 后续要接：
       - delete 后 reload 列表 + 若删的是 current 则 clearMessages
       - select 后 useConfigChat.loadHistory(sid)
       - new 后 useConfigChat.clearMessages()
       - rename 后 reload 列表
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  configChatApi,
  type ConfigChatSessionSummary,
} from '@/api/configChat'

const props = defineProps<{
  applicationId: number
  currentSessionId: number | null
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'select', sid: number): void
  (e: 'new'): void
  (e: 'delete', sid: number): void
  (e: 'rename', sid: number, title: string): void
  (e: 'update:open', val: boolean): void
}>()

const sessions = ref<ConfigChatSessionSummary[]>([])
const loading = ref(false)
const errorMsg = ref('')

async function loadSessions() {
  if (!props.applicationId) return
  loading.value = true
  errorMsg.value = ''
  try {
    sessions.value = await configChatApi.listSessions(props.applicationId)
  } catch (e: any) {
    errorMsg.value = e?.message || '加载会话失败'
    sessions.value = []
  } finally {
    loading.value = false
  }
}

// 抽屉首次打开 + 每次重新打开都拉新列表
watch(
  () => props.open,
  (v) => {
    if (v) loadSessions()
  },
)

// applicationId 变化 (用户切应用) 也刷新
watch(
  () => props.applicationId,
  () => {
    if (props.open) loadSessions()
  },
)

// 暴露 reload 方法给父组件 (父组件 send 完后想刷新列表时用)
defineExpose({ reload: loadSessions })

onMounted(() => {
  if (props.open) loadSessions()
})

function close() {
  emit('update:open', false)
}

function onPickSession(sid: number) {
  emit('select', sid)
  close()
}

function onNewSession() {
  emit('new')
  close()
}

function onDelete(sid: number, title: string, e: MouseEvent) {
  e.stopPropagation()
  if (!confirm(`确定删除会话「${title}」？此操作不可恢复。`)) return
  emit('delete', sid)
}

function onRename(sid: number, oldTitle: string, e: MouseEvent) {
  e.stopPropagation()
  const next = prompt('修改会话标题', oldTitle)
  if (next == null) return
  const trimmed = next.trim()
  if (!trimmed || trimmed === oldTitle) return
  emit('rename', sid, trimmed)
}

// 时间友好显示 (今天 HH:mm / 昨天 / N 天前 / YYYY-MM-DD)
const now = computed(() => Date.now())
function formatTime(iso: string): string {
  if (!iso) return ''
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return iso
  const diffMs = now.value - ts
  const day = 24 * 3600 * 1000
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  if (diffMs < day) return `今天 ${hh}:${mm}`
  if (diffMs < 2 * day) return `昨天 ${hh}:${mm}`
  if (diffMs < 7 * day) return `${Math.floor(diffMs / day)} 天前`
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
</script>

<template>
  <Teleport to="body">
    <!-- overlay (点击关闭) -->
    <div
      v-if="open"
      class="cas-drawer-overlay"
      data-design="v2"
      @click="close"
    />

    <!-- 抽屉本体 -->
    <aside
      v-if="open"
      class="cas-drawer"
      data-design="v2"
      role="dialog"
      aria-label="配置助手会话历史"
      @keydown.esc="close"
    >
      <header class="cas-drawer-head">
        <span class="cas-drawer-title">会话历史</span>
        <button class="cas-icon-btn" title="关闭" @click="close">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 6 6 18" /><path d="m6 6 12 12" />
          </svg>
        </button>
      </header>

      <div class="cas-drawer-actions">
        <button class="cas-new-btn" @click="onNewSession">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 5v14" /><path d="M5 12h14" />
          </svg>
          新对话
        </button>
      </div>

      <div class="cas-drawer-body">
        <div v-if="loading" class="cas-state-hint">正在加载…</div>
        <div v-else-if="errorMsg" class="cas-state-hint cas-state-error">
          {{ errorMsg }}
        </div>
        <div v-else-if="!sessions.length" class="cas-state-hint">
          暂无历史会话<br />点击 "+ 新对话" 开始
        </div>
        <ul v-else class="cas-list">
          <li
            v-for="s in sessions"
            :key="s.id"
            class="cas-item"
            :class="{ 'is-active': s.id === currentSessionId }"
            @click="onPickSession(s.id)"
          >
            <div class="cas-item-row">
              <span class="cas-item-title" :title="s.title">{{ s.title }}</span>
              <span class="cas-item-time">{{ formatTime(s.updated_at) }}</span>
            </div>
            <div v-if="s.last_message_preview" class="cas-item-preview">
              {{ s.last_message_preview }}
            </div>
            <div class="cas-item-meta">
              <span class="cas-item-count">{{ s.message_count }} 条</span>
              <span class="cas-item-actions">
                <button
                  class="cas-icon-btn cas-icon-btn-small"
                  title="改标题"
                  @click="(e) => onRename(s.id, s.title, e)"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                  </svg>
                </button>
                <button
                  class="cas-icon-btn cas-icon-btn-small cas-icon-btn-danger"
                  title="删除"
                  @click="(e) => onDelete(s.id, s.title, e)"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3 6h18" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                    <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </span>
            </div>
          </li>
        </ul>
      </div>
    </aside>
  </Teleport>
</template>

<style scoped>
/* overlay 半透明背景, 点击关闭抽屉 */
.cas-drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 1100;
  animation: cas-fade-in 0.15s ease;
}

/* 抽屉本体 — 从右侧滑出 (相对 ConfigAssistantPanel 来说是它的左侧, 因为 panel 在主屏右边) */
/* 实际位置: 浏览器右上角往左偏 panel 宽 (~ 420px) */
.cas-drawer {
  position: fixed;
  top: 0;
  bottom: 0;
  right: 0;
  width: 320px;
  background: var(--surface);
  border-left: 1px solid var(--line);
  z-index: 1101;
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 16px rgba(0, 0, 0, 0.08);
  animation: cas-slide-in 0.18s ease;
}

@keyframes cas-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes cas-slide-in {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

/* head */
.cas-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
}

.cas-drawer-title {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}

/* actions row — "+ 新对话" 大按钮置顶 */
.cas-drawer-actions {
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}

.cas-new-btn {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border: 0;
  border-radius: var(--r-2, 4px);
  background: var(--brand);
  color: var(--text-inverse, #fff);
  font-family: inherit;
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  transition: background 0.12s ease;
}

.cas-new-btn:hover {
  background: var(--brand-hover);
}

/* body — sessions list */
.cas-drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px 16px;
}

.cas-state-hint {
  padding: 32px 16px;
  font-size: 12px;
  color: var(--text-3);
  text-align: center;
  line-height: 1.6;
}

.cas-state-error {
  color: var(--danger, #d33);
}

.cas-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cas-item {
  padding: 10px 12px;
  border-radius: var(--r-2, 4px);
  cursor: pointer;
  transition: background 0.12s ease;
  border: 1px solid transparent;
}

.cas-item:hover {
  background: var(--surface-2);
}

.cas-item.is-active {
  background: var(--surface-2);
  border-color: var(--brand-ring, var(--brand));
}

.cas-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.cas-item-title {
  flex: 1;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cas-item-time {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-3);
}

.cas-item-preview {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-3);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cas-item-meta {
  margin-top: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cas-item-count {
  font-size: 11px;
  color: var(--text-4);
}

/* hover 出现 action icons; 默认隐藏避免视觉噪声 */
.cas-item-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.12s ease;
}

.cas-item:hover .cas-item-actions,
.cas-item.is-active .cas-item-actions {
  opacity: 1;
}

/* icon button 通用 */
.cas-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  border-radius: var(--r-2, 4px);
  transition: all 0.12s ease;
}

.cas-icon-btn:hover {
  background: var(--surface-3, var(--surface-2));
  color: var(--text);
}

.cas-icon-btn-small {
  width: 22px;
  height: 22px;
}

.cas-icon-btn-danger:hover {
  color: var(--danger, #d33);
  background: var(--surface-3, var(--surface-2));
}
</style>

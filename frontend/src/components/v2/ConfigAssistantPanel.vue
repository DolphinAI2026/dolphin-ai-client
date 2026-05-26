<!-- frontend/src/components/v2/ConfigAssistantPanel.vue
     Right-column panel for post-deploy `/chat?app_id=X` — users chat in
     natural language to adjust an already-deployed application.

     2026-05-24 (refactor #9): 1207 行单文件 → 5 子组件 + 4 composables 拆分:
     - ConfigAssistantHeader.vue       (标题 + 副标题 + 模型选择 dropdown — Agent B)
     - ConfigAssistantViewport.vue     (MJPEG mini preview)
     - ConfigAssistantMessages.vue     (主消息区 + plan card + hero CTA + change_plan info)
     - ConfigAssistantInput.vue        (输入框 + send btn)
     - ConfigAssistantSessionDrawer.vue (会话历史抽屉 — Agent A, 主容器集成于本文件)
     - composables/useConfigChat.ts    (messages / send / SSE 消费 / extractPlan / sessionId)
     - composables/useDynamicExamples.ts (例子 chip 按真实 SPEC 动态生成)
     - composables/useViewportStream.ts  (MJPEG 流 URL)
     - composables/usePanelResize.ts     (PointerEvent + setPointerCapture 拖宽)

     2026-05-24 (Agent A + B 集成):
     - sessionId 持久化 (useConfigChat 内, sticky from 'started' SSE event)
     - 新对话 / 历史抽屉 (SessionDrawer + drawerOpen state)
     - modelId v-model (Header dropdown, localStorage 持久化 key apaas-config-assistant-model-v1)

     props / emit / localStorage key 兼容老版本, ChatPage.vue 不动. -->
<script setup lang="ts">
import { computed, onMounted, onUpdated, ref, toRef, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import ConfigAssistantHeader from './config-assistant/ConfigAssistantHeader.vue'
import ConfigAssistantViewport from './config-assistant/ConfigAssistantViewport.vue'
import ConfigAssistantMessages from './config-assistant/ConfigAssistantMessages.vue'
import ConfigAssistantInput from './config-assistant/ConfigAssistantInput.vue'
import ConfigAssistantSessionDrawer from './config-assistant/ConfigAssistantSessionDrawer.vue'
import DeployHistoryDrawer from './DeployHistoryDrawer.vue'

import { useConfigChat } from './config-assistant/composables/useConfigChat'
import { useDynamicExamples } from './config-assistant/composables/useDynamicExamples'
import { useViewportStream } from './config-assistant/composables/useViewportStream'
import { usePanelResize } from './config-assistant/composables/usePanelResize'

import { configChatApi } from '@/api/configChat'

const props = defineProps<{
  applicationId: number
  appName?: string
  /**
   * 2026-05-26 (PR2c SPEC v2 §1.2): SectionNav 当前 section 软引导.
   * 父 ChatPage 跟左侧 SectionNav 同步, send 时透传给后端加 focus hint.
   * undefined / null / 空串 → 后端不加 hint (跟老行为兼容).
   *
   * 接受新旧两套语义 (跟 ChatPage 真实状态对齐):
   *   - 老 SECTION 系: data/ui/logic/permission/extension
   *   - 新 topTab 系: design/data/logic/perm/log
   * quickActionChips computed 内部归一化到 topTab 系再匹配 chip 集合.
   */
  currentSection?: string | null
  /**
   * 2026-05-26 (quick action chips): 当前 sub-tab.
   * 跟 currentSection 一起决定顶部 chips 集合.
   *   design: menus / forms / lists
   *   data:   models / dicts
   *   logic:  processes / events
   *   perm:   roles / field_perm / menu_vis
   *   log:    op_log / deploy_history
   */
  currentSectionTab?: string | null
}>()

const emit = defineEmits<{
  /** 2026-05-21 Phase 2: 完成态 hero CTA 触发父组件刷新 iframe */
  (e: 'refresh-iframe'): void
  /** 2026-05-25: 浮动模式 — 关闭面板回到 FAB */
  (e: 'close'): void
}>()

// 拖宽 — 学 super-agents-dev PointerEvent + setPointerCapture, 比老 mousedown 稳
const { panelWidth, isResizing, onResizeStart } = usePanelResize({
  storageKey: 'apaas-config-assistant-width-v1',
  defaultWidth: 420,
  minWidth: 320,
  maxWidth: 880,
})

// MJPEG viewport
const appIdRef = toRef(props, 'applicationId')
const { viewportEnabled, viewportStreamUrl, openViewportFull } = useViewportStream(appIdRef)

// 动态例子 chip (按当前应用真实 SPEC 生成)
const { examples } = useDynamicExamples(appIdRef)

// 2026-05-24 Agent B 集成: modelId 持久化, 跟 Header v-model 绑
const MODEL_KEY = 'apaas-config-assistant-model-v1'
const modelId = ref<number | null>((() => {
  const v = localStorage.getItem(MODEL_KEY)
  if (!v || v === 'null' || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : null
})())
watch(modelId, (v) => {
  try {
    localStorage.setItem(MODEL_KEY, v == null ? '' : String(v))
  } catch {
    /* private mode */
  }
})

// Chat 核心逻辑 — scrollerRef 在 onMounted 后 querySelector 注入
const scrollerRef = ref<HTMLElement | null>(null)
const {
  messages,
  input,
  sending,
  send,
  pickExample,
  // Agent A 新增 exports
  sessionId,
  clearMessages,
  loadHistory,
} = useConfigChat({
  applicationId: appIdRef,
  scrollerRef,
  modelId, // Agent B
  currentSection: toRef(props, 'currentSection') as any, // PR2c (SPEC v2 §1.2)
})

// 2026-05-24 Agent A 集成: 历史会话抽屉
const drawerOpen = ref(false)
const drawerRef = ref<InstanceType<typeof ConfigAssistantSessionDrawer> | null>(null)

// 2026-05-24 Agent C 集成: 部署历史抽屉 (post-deploy 应用专属入口)
const deployHistoryOpen = ref(false)

async function onDelete(sid: number) {
  try {
    await ElMessageBox.confirm('确定删除这条会话?', '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await configChatApi.deleteSession(sid)
    if (sid === sessionId.value) clearMessages()
    drawerRef.value?.reload()
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}

async function onRename(sid: number, title: string) {
  try {
    await configChatApi.updateSessionTitle(sid, title)
    drawerRef.value?.reload()
  } catch (e: any) {
    ElMessage.error(e?.message || '改标题失败')
  }
}

async function onSelectSession(sid: number) {
  drawerOpen.value = false
  try {
    await loadHistory(sid)
  } catch (e: any) {
    ElMessage.error(e?.message || '加载历史失败')
  }
}

function onNewSession() {
  drawerOpen.value = false
  clearMessages()
}

const emptyHint = computed(
  () => `配置「${props.appName ?? '应用'}」— 描述你想调整的字段、流程、权限...`,
)

// ─── Quick action chips ────────────────────────────────────────
// 2026-05-26: 按 currentSection + currentSectionTab 智能切快捷指令.
// 用户点 chip → input prefill (不直接发送, 留 review/edit 空间).

interface QuickActionChip {
  label: string
  prompt: string
}

// 老 SECTION 系 → topTab 系归一化, chip 表只按 topTab 维护一份.
const SECTION_TO_TOP: Record<string, string> = {
  ui: 'design',
  data: 'data',
  logic: 'logic',
  permission: 'perm',
  extension: 'log',
  // topTab 系自身原样透传 (容错 ChatPage 任一种语义)
  design: 'design',
  perm: 'perm',
  log: 'log',
}

// (topTab, sub-tab) → chip 集合. 没匹配时 fallback 到 default 集合.
const CHIP_MATRIX: Record<string, QuickActionChip[]> = {
  'design:menus': [
    { label: '分析当前菜单', prompt: '请分析当前应用的菜单结构，列出各菜单对应的表单/列表配置情况' },
    { label: '新建菜单', prompt: '请帮我新建一个菜单，名字叫「」，绑定到表单「」' },
    { label: '调整菜单顺序', prompt: '请把菜单「」调整到第「」位' },
  ],
  'design:forms': [
    { label: '分析当前表单', prompt: '请分析当前表单的字段结构，列出字段名/类型/必填情况' },
    { label: '添加字段', prompt: '请帮我在表单里添加一个字段：字段名「」、类型「」、是否必填「」' },
    { label: '生成测试数据', prompt: '请帮我为当前表单生成 5 条测试数据' },
    { label: '改字段必填', prompt: '请把字段「」改为「必填 / 非必填」' },
  ],
  'design:lists': [
    { label: '分析列表配置', prompt: '请分析当前列表的列配置：显示哪些字段、排序、筛选条件' },
    { label: '添加列', prompt: '请帮我在列表里添加一列：字段「」' },
    { label: '调整列顺序', prompt: '请把列「」调整到第「」位' },
  ],
  'data:models': [
    { label: '看模型结构', prompt: '请展示当前数据模型的完整字段定义（字段名/类型/约束）' },
    { label: '加字段', prompt: '请在模型里加一个字段：字段名「」、类型「」' },
    { label: '改字段类型', prompt: '请把字段「」的类型从「」改成「」' },
  ],
  'data:dicts': [
    { label: '添加字典选项', prompt: '请在字典「」里添加选项：值「」、显示名「」' },
    { label: '新建字典', prompt: '请帮我新建一个字典：名字「」、用于「」' },
    { label: '看字典选项', prompt: '请列出字典「」的全部选项' },
  ],
  'logic:processes': [
    { label: '看流程节点', prompt: '请展示当前流程的全部节点（开始/审批/分支/结束）以及流转规则' },
    { label: '加审批节点', prompt: '请在流程里加一个审批节点：审批人「」、位置「」' },
    { label: '改流程分支', prompt: '请帮我把流程的分支条件改成：「」' },
  ],
  'logic:events': [
    { label: '看业务事件', prompt: '请列出当前应用配置的全部业务事件以及触发条件' },
    { label: '新建业务事件', prompt: '请帮我新建一个业务事件：触发条件「」、动作「」' },
  ],
  'perm:roles': [
    { label: '新建角色', prompt: '请帮我新建一个角色：名字「」、权限范围「」' },
    { label: '给角色加成员', prompt: '请把用户「」加到角色「」' },
    { label: '看角色配置', prompt: '请列出当前应用所有角色及其成员/权限范围' },
  ],
  'perm:field_perm': [
    { label: '看字段权限', prompt: '请列出当前应用的字段级权限配置（哪些角色看不到哪些字段）' },
    { label: '改字段权限', prompt: '请把字段「」对角色「」改成「只读 / 隐藏 / 可写」' },
  ],
  'perm:menu_vis': [
    { label: '看菜单可见性', prompt: '请列出菜单可见性配置（哪些角色看不到哪些菜单）' },
    { label: '改菜单可见性', prompt: '请把菜单「」对角色「」改成「可见 / 不可见」' },
  ],
  'log:op_log': [
    { label: '查最近操作', prompt: '请查一下最近 1 天的操作日志' },
  ],
  'log:deploy_history': [
    { label: '查部署历史', prompt: '请列出最近 5 次的部署记录及结果' },
  ],
}

const DEFAULT_CHIPS: QuickActionChip[] = [
  { label: '分析当前应用', prompt: '请分析当前应用的整体结构：菜单/表单/模型/角色/流程' },
  { label: '添加字段', prompt: '请帮我在表单里添加一个字段：字段名「」、类型「」' },
  { label: '新建表单', prompt: '请帮我新建一个表单：名字「」、绑定模型「」' },
]

const quickActionChips = computed<QuickActionChip[]>(() => {
  const rawSection = (props.currentSection ?? '').trim()
  if (!rawSection) return DEFAULT_CHIPS
  const top = SECTION_TO_TOP[rawSection] || rawSection
  const sub = (props.currentSectionTab ?? '').trim()
  if (!sub) return DEFAULT_CHIPS
  return CHIP_MATRIX[`${top}:${sub}`] || DEFAULT_CHIPS
})

function onChipClick(chip: QuickActionChip) {
  input.value = chip.prompt
  // scrollToInput — 把焦点也带到 input 上, 让用户看到 prefill 内容.
  setTimeout(() => {
    const ta = document.querySelector(
      '.config-assistant .ca-input-area .ca-input',
    ) as HTMLTextAreaElement | null
    if (ta) {
      ta.focus()
      // cursor 移到末尾 (方便用户继续 edit)
      const len = ta.value.length
      try {
        ta.setSelectionRange(len, len)
      } catch { /* ignore */ }
    }
  }, 0)
}

onMounted(() => {
  const el = document.querySelector('.config-assistant .ca-scroll') as HTMLElement | null
  if (el) scrollerRef.value = el
})

// 兜底: 每次 updated 也强同步一次 ref (防 Messages remount 时 ref 丢)
onUpdated(() => {
  if (!scrollerRef.value) {
    const el = document.querySelector('.config-assistant .ca-scroll') as HTMLElement | null
    if (el) scrollerRef.value = el
  }
})
</script>

<template>
  <aside
    class="config-assistant"
    data-design="v2"
    :class="{ 'is-resizing': isResizing }"
    :style="{ width: panelWidth + 'px' }"
  >
    <!-- 左边缘拖拽 handle -->
    <div class="ca-resize-handle" @pointerdown="onResizeStart" title="拖拽调整宽度" />

    <!-- 顶部 actions: 新对话 / 历史 / 部署历史 (固定在 panel 顶部右上角) -->
    <div class="ca-top-actions">
      <button
        class="ca-top-btn"
        title="新对话"
        @click="onNewSession"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
      <button
        class="ca-top-btn"
        title="历史对话"
        @click="drawerOpen = true"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 7h18M3 12h18M3 17h18" />
        </svg>
      </button>
      <button
        class="ca-top-btn"
        title="部署历史 / 回滚"
        @click="deployHistoryOpen = true"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 8v4l3 2" />
          <circle cx="12" cy="12" r="9" />
        </svg>
      </button>
      <!-- 2026-05-25: 浮动模式 close 按钮 -->
      <button
        class="ca-top-btn"
        title="收起助手"
        @click="$emit('close')"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 6L6 18M6 6l12 12" />
        </svg>
      </button>
    </div>

    <ConfigAssistantHeader :app-name="appName" v-model:model-id="modelId" />

    <ConfigAssistantViewport
      :enabled="viewportEnabled"
      :stream-url="viewportStreamUrl"
      @toggle="viewportEnabled = $event"
      @open-full="openViewportFull"
    />

    <!-- Quick action chips — 按 currentSection + currentSectionTab 智能切.
         点 chip 把 prompt 文本填到 input (不直接发送, 让用户 review/edit). -->
    <div v-if="quickActionChips.length" class="ca-quick-actions" role="toolbar" aria-label="快捷指令">
      <button
        v-for="chip in quickActionChips"
        :key="chip.label"
        class="ca-chip"
        type="button"
        :title="chip.prompt"
        @click="onChipClick(chip)"
      >
        {{ chip.label }}
      </button>
    </div>

    <ConfigAssistantMessages
      :messages="messages"
      :examples="examples"
      :sending="sending"
      :empty-hint="emptyHint"
      @pick-example="pickExample"
      @refresh-iframe="emit('refresh-iframe')"
    />

    <ConfigAssistantInput
      v-model="input"
      :sending="sending"
      @send="send"
    />

    <!-- 会话历史抽屉 (Agent A 新组件, 主容器集成) -->
    <ConfigAssistantSessionDrawer
      ref="drawerRef"
      v-model:open="drawerOpen"
      :application-id="applicationId"
      :current-session-id="sessionId"
      @select="onSelectSession"
      @new="onNewSession"
      @delete="onDelete"
      @rename="onRename"
    />

    <!-- 部署历史抽屉 (Agent C 新组件, post-deploy 应用专属入口) -->
    <DeployHistoryDrawer
      v-model:open="deployHistoryOpen"
      :application-id="applicationId"
      :app-name="appName"
      @rolled-back="emit('refresh-iframe')"
    />
  </aside>
</template>

<style scoped>
.config-assistant {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  border-left: 1px solid var(--line);
  background: var(--surface);
  flex-shrink: 0;
  overflow: hidden;
}

.config-assistant.is-resizing {
  cursor: ew-resize;
  user-select: none;
}

/* ─── 拖拽 handle (左边缘 5px) ───────────────────────────── */
.ca-resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 5px;
  cursor: ew-resize;
  z-index: 10;
  transition: background 0.12s ease;
  touch-action: none;
}

.ca-resize-handle:hover,
.config-assistant.is-resizing .ca-resize-handle {
  background: var(--brand-ring, var(--brand));
  opacity: 0.4;
}

/* ─── 顶部 actions (新对话 / 历史) ────────────────────────── */
.ca-top-actions {
  position: absolute;
  top: 8px;
  right: 10px;
  display: flex;
  gap: 4px;
  z-index: 5;
}

.ca-top-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 4px);
  background: var(--surface);
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.12s ease;
}

.ca-top-btn:hover {
  border-color: var(--brand);
  color: var(--brand);
}

/* ─── Quick action chips (顶部快捷指令) ───────────────────── */
.ca-quick-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  flex-shrink: 0;
}

.ca-quick-actions::-webkit-scrollbar {
  height: 4px;
}

.ca-quick-actions::-webkit-scrollbar-thumb {
  background: var(--line);
  border-radius: 2px;
}

.ca-chip {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-2, var(--surface));
  color: var(--text-2, var(--text));
  font-family: inherit;
  font-size: 14px;
  font-weight: var(--fw-regular, 400);
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.12s ease;
}

.ca-chip:hover {
  border-color: var(--brand);
  background: color-mix(in srgb, var(--brand) 8%, var(--surface));
  color: var(--brand);
}

.ca-chip:active {
  transform: translateY(1px);
}

.ca-chip:focus-visible {
  outline: 2px solid var(--brand-ring, var(--brand));
  outline-offset: 1px;
}
</style>

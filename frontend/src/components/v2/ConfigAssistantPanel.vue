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
  /**
   * 2026-05-26 design-v4 Polish F1 / K1: 设计 tab + 选中菜单后的 designer sub-tab.
   * 取值 form / list / process / data / page (跟 ChatPage DESIGNER_SUBS 对齐).
   * 父在 design tab 且 selectedApaasMenuId 存在时传, 否则传 null.
   * 优先级: designerSub 非空 → 走 `designer:<sub>` chip 集合; 否则走老 currentSection+sub.
   *
   * K1 修复历史 (2026-05-26): F1 commit f760198 加过, 但 I2 commit c5862da
   * 用 stale base 把 F1 改动整段覆盖丢. 本次 K1 重新加回 + watch + 加 design-v4
   * 用户截图 bug (在流程设计 sub 但 chips 还显权限) 的 root cause 治掉.
   */
  designerSub?: string | null
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
//
// 2026-05-26 design-v4 Polish F1 / K1: 设计 tab 选中菜单后走 designer:* 系
// (form/list/process/data/page), 跟 ChatPage.DESIGNER_SUBS 一一对应.
// 顶级 SECTION → topTab 映射在 SECTION_TO_TOP, designer:* 由 props.designerSub
// 直接命中, 不走映射.
const CHIP_MATRIX: Record<string, QuickActionChip[]> = {
  // ─── design (设计 tab, 未选菜单) ──────────────────────────
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

  // ─── designer:* (设计 tab, 选中菜单后顶部 4 sub-tab) ──────
  // FormDesignerPanel (表单设计)
  'designer:form': [
    { label: '按使用频率排序字段', prompt: '请把当前表单的字段按使用频率从高到低排序，最常用的放前面' },
    { label: '加金额字段 必填', prompt: '请给当前表单加一个金额字段，名字叫「金额」，类型 number，必填，最大值 50000' },
    { label: '所有日期字段默认今天', prompt: '请把当前表单里所有日期字段的默认值都设置为「今天」' },
    { label: '生成 5 条测试数据', prompt: '请帮我为当前表单生成 5 条测试数据，字段值要符合业务语义' },
  ],
  // ListDesignerPanel (列表设计)
  'designer:list': [
    { label: '加搜索框 图书名称', prompt: '请给当前列表加一个搜索框，按图书名称搜索' },
    { label: '默认按申请日期倒序', prompt: '请把当前列表的默认排序改成按申请日期倒序排列' },
    { label: '加 5 个查询条件', prompt: '请给当前列表加 5 个查询条件：借阅人、状态、申请日期范围（起始）、申请日期范围（结束）、归还日期' },
  ],
  // ProcessDesignerPanel (流程设计)
  'designer:process': [
    { label: '加部门主管→总监审批', prompt: '请给当前流程加一个审批流：先部门主管审批，通过后再到总监审批' },
    { label: '改成会签', prompt: '请把当前流程的审批节点改成「会签」模式（所有审批人都同意才通过）' },
    { label: '超 24h 自动通过', prompt: '请给当前流程加超时规则：审批节点超过 24 小时未处理，自动通过' },
    { label: '加 webhook 通知', prompt: '请给当前流程加一个 webhook 通知节点：流程结束后回调指定 URL' },
  ],
  // DataSchemaEditor (数据 schema, 设计 tab 内 sub)
  'designer:data': [
    { label: '加 created_at / updated_at', prompt: '请给当前数据模型加 created_at 和 updated_at 两个时间戳字段（自动维护）' },
    { label: 'status 字段加索引', prompt: '请给当前数据模型的 status 字段加一个普通索引' },
    { label: '分析字段命名规范', prompt: '请分析当前数据表的字段命名规范，指出不一致的地方并给出统一建议' },
    { label: '推荐 3 个候选索引', prompt: '请根据当前表的字段定义和典型查询模式，推荐 3 个可以加的候选索引' },
  ],
  // 页面设置 (设计 tab 内 sub, P1 placeholder)
  'designer:page': [
    { label: '改 title 为 XXX', prompt: '请把当前页面的 title 改成「」' },
    { label: '图标换成 📅', prompt: '请把当前菜单的图标换成「📅」' },
    { label: '加默认权限规则', prompt: '请给当前页面加一个默认权限规则：用户只能看到自己创建的记录' },
  ],

  // ─── data tab (数据) ──────────────────────────────────
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
  // 2026-05-26 F1: 权限矩阵 view 主用 chips (跟 RoleManagePanel 矩阵 UI 对齐)
  'perm:roles': [
    { label: '管理员开所有权限', prompt: '请给「管理员」角色开通所有页面和所有数据的全部权限（可读 + 可写 + 可删除）' },
    { label: '加角色 财务', prompt: '请新加一个角色叫「财务」，默认权限范围设置为相关数据可读' },
    { label: '审批人全只读', prompt: '请把「审批人」角色对所有页面的权限改成只读' },
  ],
  // perm:matrix 跟 perm:roles 同义 (RoleManagePanel viewMode 切换时如果未来透传 matrix 也走同 chips)
  'perm:matrix': [
    { label: '管理员开所有权限', prompt: '请给「管理员」角色开通所有页面和所有数据的全部权限（可读 + 可写 + 可删除）' },
    { label: '加角色 财务', prompt: '请新加一个角色叫「财务」，默认权限范围设置为相关数据可读' },
    { label: '审批人全只读', prompt: '请把「审批人」角色对所有页面的权限改成只读' },
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
  // 2026-05-26 F1 / K1: designer mode 优先 — design tab + 选中菜单后,
  // ChatPage 把 designerSub (form/list/process/data/page) 透传过来,
  // 这时 chips 直接走 designer:<sub> 集合, 跟当前 panel UI 对齐.
  //
  // K1 修 bug: 用户在设计 tab + 选中菜单 + 切到 "流程设计" sub 时,
  // 老代码只看 currentSection+currentSectionTab — 但 ChatPage 在 design tab
  // 内部切 designer sub-tab 时只改 designerSub ref, 不改 currentSectionTab,
  // 所以 chips 一直停在切 topTab 时的旧 sub (常见情形: 用户先在 perm tab,
  // 然后切到 design + 选菜单, currentSection 变 ui 但 currentSectionTab
  // 还停在 perm 残留值, chips 就显权限相关). 加 designerSub 优先级根治.
  const ds = (props.designerSub ?? '').trim()
  if (ds) {
    return CHIP_MATRIX[`designer:${ds}`] || DEFAULT_CHIPS
  }
  const rawSection = (props.currentSection ?? '').trim()
  if (!rawSection) return DEFAULT_CHIPS
  const top = SECTION_TO_TOP[rawSection] || rawSection
  const sub = (props.currentSectionTab ?? '').trim()
  if (!sub) return DEFAULT_CHIPS
  return CHIP_MATRIX[`${top}:${sub}`] || DEFAULT_CHIPS
})

// 2026-05-26 (I2): chip click 真发 message — 占位 chip 只 prefill, 实指令直接发.
// 占位标记: prompt 含 「」 (中文角括号成对) / 「…」 / XX (待用户填值).
function chipHasPlaceholder(prompt: string): boolean {
  return /「[^」]*」/.test(prompt) || prompt.includes('…') || /\bXX\b/.test(prompt)
}

// chip 点击高亮闪烁 (0.15s 蓝 ring) — flashingChip = chip.label, CSS 用 :class 加 is-flashing
const flashingChip = ref<string | null>(null)
// 自动发送中的 chip — 显 inline loading dot
const autoSendingChip = ref<string | null>(null)

async function onChipClick(chip: QuickActionChip) {
  // 边界 1: 没选中应用
  if (!props.applicationId || props.applicationId <= 0) {
    ElMessage.warning('请先选应用')
    return
  }
  // 边界 2: 正在发送 — 防重入
  if (sending.value) {
    ElMessage.info('正在发送中, 请稍候')
    return
  }

  // 视觉: chip 高亮闪 0.15s
  flashingChip.value = chip.label
  setTimeout(() => {
    if (flashingChip.value === chip.label) flashingChip.value = null
  }, 200)

  // 边界 3: input 已有内容 — 直接覆盖 (用户决策: 覆盖更轻快, confirm 太烦)
  input.value = chip.prompt

  if (chipHasPlaceholder(chip.prompt)) {
    // 占位 chip: 只 prefill, focus 让用户填值
    setTimeout(() => {
      const ta = document.querySelector(
        '.config-assistant .ca-input-area .ca-input',
      ) as HTMLTextAreaElement | null
      if (ta) {
        ta.focus()
        // 找第一个「」位置, 把光标放到「」之间方便用户立即输入
        const m = ta.value.match(/「[^」]*」/)
        if (m && m.index != null) {
          const pos = m.index + 1
          try {
            ta.setSelectionRange(pos, pos + (m[0].length - 2))
          } catch { /* ignore */ }
        } else {
          const len = ta.value.length
          try {
            ta.setSelectionRange(len, len)
          } catch { /* ignore */ }
        }
      }
    }, 0)
    return
  }

  // 实指令 — 自动发送 (跟 input + send btn 同路径)
  autoSendingChip.value = chip.label
  try {
    await send()
  } catch (e: any) {
    // send() 自身已 toast 错误, 这里兜底
    ElMessage.error(e?.message || '发送失败')
  } finally {
    autoSendingChip.value = null
  }
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
         2026-05-26 (I2): 真发送链路.
         - prompt 含 「」/「…」/XX 占位: 只 prefill, 让用户填值后自己 click send.
         - 实指令 (无占位): 自动 send() 真发到 backend SSE endpoint.
         视觉: click 闪 0.15s 蓝 ring; 自动发送中显 inline loading dot. -->
    <div v-if="quickActionChips.length" class="ca-quick-actions" role="toolbar" aria-label="快捷指令">
      <button
        v-for="chip in quickActionChips"
        :key="chip.label"
        class="ca-chip"
        :class="{
          'is-flashing': flashingChip === chip.label,
          'is-sending': autoSendingChip === chip.label,
          'is-placeholder': chipHasPlaceholder(chip.prompt),
        }"
        type="button"
        :title="chipHasPlaceholder(chip.prompt) ? '点击预填, 修改后发送' : chip.prompt"
        :disabled="sending && autoSendingChip !== chip.label"
        @click="onChipClick(chip)"
      >
        {{ chip.label }}
        <span v-if="autoSendingChip === chip.label" class="ca-chip-dot" aria-hidden="true" />
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

/* 2026-05-26 (I2): chip 状态视觉 — flash / sending / placeholder. */
.ca-chip[disabled] {
  opacity: 0.5;
  cursor: not-allowed;
}

.ca-chip.is-flashing {
  animation: ca-chip-flash 0.2s ease;
}

@keyframes ca-chip-flash {
  0% {
    box-shadow: 0 0 0 0 var(--brand-ring, var(--brand));
    background: color-mix(in srgb, var(--brand) 20%, var(--surface));
  }
  100% {
    box-shadow: 0 0 0 4px transparent;
    background: var(--surface-2, var(--surface));
  }
}

.ca-chip.is-sending {
  border-color: var(--brand);
  color: var(--brand);
  background: color-mix(in srgb, var(--brand) 12%, var(--surface));
  cursor: default;
  opacity: 1;
}

/* 占位 chip — 加 dashed 下划线提示"需填值" */
.ca-chip.is-placeholder {
  border-style: dashed;
}

/* 自动发送 inline loading dot */
.ca-chip-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-left: 6px;
  border-radius: 50%;
  background: var(--brand);
  animation: ca-chip-dot-pulse 1s ease infinite;
}

@keyframes ca-chip-dot-pulse {
  0%, 100% {
    opacity: 0.3;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.2);
  }
}
</style>

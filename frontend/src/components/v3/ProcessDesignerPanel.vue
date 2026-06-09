<!-- ProcessDesignerPanel.vue — Native 流程设计器面板 (只读自渲拓扑 + 深链低代码后台).

  2026-06-04: 去内嵌编辑 + 去 mock 实例 — 只读流程拓扑 + 「打开低代码后台」深链。
    删 业务/设计 切换 / ApaasEmbedIframe 内嵌 / ProcessNodePropsPanel / 编辑机器
    (onSave/onDeploy/serializeGraph) / mock 实例进度(banner / 时间轴 / 节点着色)。
    留 x6 只读画布 + 节点拓扑; renderDefinition 后自动 onFitContent 适应视口。
    ⚠️ 以下为历史 changelog, 多数功能已删。

  2026-05-27 O2-Process: 业务视角强化 — view-mode 像在看运行实例进度.
    - view (默认): 顶部蓝色 banner "申请单 SQDH-2026-001 提交于 3 分钟前", 左 sidebar / 右属性面板隐藏,
      x6 节点按 mock instance 状态着色 (completed 绿 / current 蓝 + 脉冲 / pending 灰),
      右侧 "历史轨迹" 时间轴 panel
    - edit: 保留 C/G/H/I/J/K 全部老逻辑 (sidebar + props panel + 拖入 + 保存 + 部署)
    - 顶 segmented control "👁 业务 / ✏️ 设计" (改流程走右栏常驻配置助手)

  2026-05-26 design-v4 Phase C: 扩 24 节点 (4 分类 × 4-5 种) + 属性面板.
    - 左 sidebar 顶部 "流程列表" panel (真拉 /section-content/processes)
    - 左 sidebar collapsible 4 分类: 入口出口 / 审批 / 逻辑 / 动作 (24 节点 chip grid 2 列)
    - 中央顶部 toolbar: 流程名称 + 节点统计 + 适应 + 编辑/查看 toggle + 保存
    - 中央 x6 canvas: 不同 shape/color 渲染 (entry 圆 / approval 圆角矩形 / logic 菱形 / action 矩形)
    - 右 ProcessNodePropsPanel: 按 node.type 显不同 props (~400 行新组件)

  2026-05-26 G2: 接真应用流程 list — 不再依赖 menuId 入口.
    - onMounted 拉 /applications/{appId}/section-content/processes
    - 左 sidebar 顶部 "流程列表" 显真流程, 选中切 canvas
    - props.formId 提示存在时尝试自动选中匹配流程 (form_id === formId)
    - 顶部 toolbar 真统计 (graph.getNodes/getEdges)
    - 编辑/查看 toggle — 默认 view (read-only 节点不可拖, 库 chip 不响应); edit 才能加
    - 没流程时显 "应用无流程, 用配置助手对话创建" empty state
    - BPMN 详情拉取 P3 (平台没 query process detail API), 留 alert 占位

  数据保存 (P2 接入):
    - 加载 reload: BPMN detail 拉取 P3, 当前空画布
    - 保存按钮: alert 提示走配置助手对话

  样式: design-v3 token (全 var 化, 仅 x6 attrs hex 在 buildNodeSpec 用原始值)
-->
<template>
  <section class="pdp" aria-label="流程设计">
    <!-- loading 应用流程 list -->
    <div v-if="loadingList" class="pdp-empty">
      <div class="pdp-empty-icon"><AppIcon name="hourglass" :size="48" /></div>
      <h3>加载流程列表...</h3>
    </div>

    <!-- 拉 list 出错 (应用未部署 / token 失效) -->
    <div v-else-if="listError" class="pdp-empty">
      <div class="pdp-empty-icon"><AppIcon name="warning" :size="48" /></div>
      <h3>加载失败</h3>
      <p>{{ listError }}</p>
      <button class="pdp-btn pdp-btn-ghost" @click="reloadProcessList">重试</button>
    </div>

    <!-- 应用无流程 — 友好空态 + 引导对话 CTA.
         注: 区别于 `pdp-canvas-hint` ("「X」尚无流程定义" 那个) — 那个是选中流程但定义空,
         这里是整个应用一个流程都没有 (例如 app_id=13 图书借阅管理系统). -->
    <div v-else-if="visibleProcessList.length === 0" class="pdp-empty pdp-empty-process">
      <div class="pdp-empty-icon" aria-hidden="true"><AppIcon name="shuffle" :size="48" /></div>
      <h3>{{ props.formId && processList.length > 0 ? '当前表单暂无流程' : '暂无业务流程' }}</h3>
      <p>
        {{
          props.formId && processList.length > 0
            ? '这个菜单还没有绑定流程；需要时可用配置助手创建，或到低代码后台配置。'
            : '用配置助手对话生成首个审批流, 例如：「为借书申请加管理员审批流程」'
        }}
      </p>
      <button
        type="button"
        class="pdp-btn pdp-btn-primary pdp-empty-cta"
        @click="onRequestConfigChat"
      >
        <AppIcon name="sparkles" :size="14" />
        用对话创建流程
      </button>
    </div>

    <!-- 有流程: 显完整设计器 -->
    <template v-else>
      <!-- 中央顶部 toolbar -->
      <header class="pdp-head">
        <div class="pdp-head-meta">
          <h1 class="pdp-title">
            {{ activeProcess?.name || activeProcess?.code || '选择左侧流程' }}
          </h1>
          <p class="pdp-sub">
            <span class="pdp-stat">{{ statsLine }}</span>
          </p>
        </div>
        <div class="pdp-head-actions">
          <OpenLowcodeBackendButton
            v-if="!hideLowcodeBtn"
            :app-id="props.appId"
            menu-type="MODEL"
            :menu-id="props.menuId || ''"
            :form-id="activeProcess?.form_id || props.formId || null"
            title="在低代码后台编辑此流程"
          />
          <!-- 适应画布: 渲染后自动适应, 此处供手动重新适应 -->
          <button class="pdp-btn pdp-btn-ghost" @click="onFitContent" title="适应画布">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7V3h4M21 7V3h-4M3 17v4h4M21 17v4h-4"/></svg>
            适应
          </button>
        </div>
      </header>

      <div class="pdp-body">
        <!-- 左 sidebar: 流程列表 (始终显) + 模式提示 -->
        <aside v-show="!assistantOpen" class="pdp-sidebar" aria-label="流程列表">
          <!-- ── 流程列表 panel ────────────────────────────────── -->
          <div class="pdp-section">
            <button
              class="pdp-section-head"
              @click="processListCollapsed = !processListCollapsed"
              :aria-expanded="!processListCollapsed"
            >
              <span class="pdp-cat-arrow" :class="{ 'is-open': !processListCollapsed }">▸</span>
              <span class="pdp-cat-label">流程列表</span>
              <span class="pdp-cat-count">{{ visibleProcessList.length }}</span>
            </button>
            <div v-if="!processListCollapsed" class="pdp-process-list">
              <button
                v-for="p in visibleProcessList"
                :key="p.id"
                class="pdp-process-item"
                :class="{ 'is-active': p.id === activeProcessId }"
                :title="`${p.name || p.code}${p.code ? ` (${p.code})` : ''}`"
                @click="onSelectProcess(p.id)"
              >
                <span class="pdp-process-icon"><AppIcon name="shuffle" :size="14" /></span>
                <span class="pdp-process-name">{{ p.name || p.code || p.id }}</span>
              </button>
            </div>
          </div>

        </aside>

        <!-- 中央 x6 canvas — 只读拓扑视图 (v-show 恒真, 保 containerRef 常驻 DOM). -->
        <div v-show="readOnly" class="pdp-canvas-wrap">
          <div ref="containerRef" class="pdp-canvas"></div>
          <div v-if="!nodeCount && activeProcess" class="pdp-canvas-hint">
            <div class="pdp-canvas-hint-icon">⊕</div>
            <p>
              <strong>"{{ activeProcess.name || activeProcess.code }}"</strong> 尚无流程定义
              <br />
              <span class="pdp-canvas-hint-sub">
                点上方「打开低代码后台」用 apaas 原生编辑器搭建流程, 或用配置助手对话快速生成
              </span>
            </p>
          </div>
          <div v-if="!activeProcess" class="pdp-canvas-hint">
            <div class="pdp-canvas-hint-icon"><AppIcon name="point-left" :size="28" /></div>
            <p>从左侧"流程列表"选择一个流程</p>
          </div>
        </div>

      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, shallowRef, reactive, nextTick } from 'vue'
import { Graph } from '@antv/x6'
import AppIcon from '@/components/common/AppIcon.vue'
import OpenLowcodeBackendButton from '@/components/v3/OpenLowcodeBackendButton.vue'
import request from '@/utils/request'
import {
  type NodeType,
  type ProcessNode,
  getNodeDef,
  getNodeCategoryCode,
  getNodeColor,
} from './processNodeRegistry'

const props = defineProps<{
  appId: number
  menuId?: string
  menuName?: string
  formId?: string
  /** 隐藏「打开低代码后台」按钮 — 该面板在设计 tab + 逻辑 tab 双处复用，
      外层 tab 条已统一承载该按钮时传 true 隐藏内部按钮，避免重复。默认显示。 */
  hideLowcodeBtn?: boolean
  /** 右侧 AI 助手是否打开 — 打开时自动收起「流程列表」侧栏给画布腾空间，
      否则助手 + 双侧栏会把画布挤窄、流程缩成一小条。 */
  assistantOpen?: boolean
}>()

const containerRef = ref<HTMLElement | null>(null)
// 画布尺寸变化(右侧助手开/关、窗口缩放)后自动重新适应 — 否则 zoomToFit 停在陈旧缩放,
// 画布被挤窄时流程会缩成一小条、跟画布完全不成比例。
let resizeObserver: ResizeObserver | null = null
let refitTimer: ReturnType<typeof setTimeout> | null = null
const graphRef = shallowRef<Graph | null>(null)
let themeObserver: MutationObserver | null = null
let lastRenderedDefinition: {
  nodes: ProcessDefinitionNodeOut[]
  edges: ProcessDefinitionEdgeOut[]
  preservePositions: boolean
} | null = null

/** 全部 node state (reactive). 每个 node = id + 各 type 配置. */
const nodeStates = reactive<Record<string, ProcessNode>>({})
const selectedNodeId = ref<string | null>(null)
const nodeCount = ref(0)
const edgeCount = ref(0)

/** 流程列表 (从 /section-content/processes 真拉). */
interface ProcessItem {
  id: string
  name: string
  code: string
  form_id?: string
  status?: string
  extra: Record<string, unknown>
}
const processList = ref<ProcessItem[]>([])
const activeProcessId = ref<string | null>(null)
const loadingList = ref(false)
const listError = ref<string | null>(null)
const processListCollapsed = ref(false)

/** 默认 read-only — toggle 切到 edit 后才能加节点 / 拖. */
const readOnly = ref(true)

/** H2: 保存按钮 loading + 上次本地保存时间 (ISO string). */
const lastSavedAt = ref<string | null>(null)


const activeProcess = computed<ProcessItem | null>(() => {
  if (!activeProcessId.value) return null
  const found = processList.value.find(p => p.id === activeProcessId.value) || null
  if (props.formId && found?.form_id !== props.formId) return null
  return found
})

// 2026-05-28: 流程列表只显示"当前表单/菜单"的流程 (用户反馈别把全应用流程都列出来)。
// props.formId 在时严格按 form_id 过滤; 当前表单没流程就显示空态, 不能兜底打开别的表单流程。
const visibleProcessList = computed<ProcessItem[]>(() => {
  const fid = props.formId
  if (!fid) return processList.value
  return processList.value.filter(p => p.form_id === fid)
})

const statsLine = computed(() => {
  const entryN = Object.values(nodeStates).filter(n => getNodeCategoryCode(n.type) === 'entry').length
  const procCount = visibleProcessList.value.length
  const procLine = procCount ? `${procCount} 个流程` : '0 个流程'
  if (!activeProcess.value) {
    return `${procLine} — 未选`
  }
  return `${procLine} · ${entryN} 入口 · ${nodeCount.value} 节点 · ${edgeCount.value} 连线`
})


function pushDisplayLabel(target: string[], value: unknown, allowOpaque = false) {
  if (value === null || value === undefined) return
  const text = String(value).trim()
  if (!text) return
  if (!allowOpaque && /^\d{10,}$/.test(text)) return
  if (!target.includes(text)) target.push(text)
}

function collectApproverLabels(value: unknown, target: string[]) {
  if (!value) return
  if (Array.isArray(value)) {
    value.forEach(item => collectApproverLabels(item, target))
    return
  }
  if (typeof value === 'object') {
    const item = value as Record<string, unknown>
    const type = String(item.type || item.approverType || '').trim().toUpperCase()
    const before = target.length
    for (const key of ['label', 'name', 'roleName', 'userName', 'displayName', 'subjectName', 'title']) {
      pushDisplayLabel(target, item[key], true)
    }
    if (target.length === before && type === 'SUBMITTER') {
      pushDisplayLabel(target, '申请人', true)
    }
    return
  }
  pushDisplayLabel(target, value)
}

function processApproverDisplay(props: Record<string, unknown> | undefined): string {
  if (!props) return ''
  const labels: string[] = []
  for (const key of [
    'approverLabels',
    'approver_labels',
    'approverNames',
    'approver_names',
    'roleLabels',
    'role_names',
  ]) {
    collectApproverLabels(props[key], labels)
  }
  if (!labels.length) collectApproverLabels(props.approvers, labels)
  if (!labels.length) return ''
  const head = labels.slice(0, 2).join('、')
  return labels.length > 2 ? `${head} 等${labels.length}个` : head
}

interface ProcessGraphPalette {
  canvasBg: string
  gridColor: string
  nodeFill: string
  nodeText: string
  nodeSubText: string
  endpointStroke: string
  edgeStroke: string
  edgeLabelFill: string
  edgeLabelStroke: string
  edgeLabelText: string
  shadowColor: string
}

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function isDarkTheme(): boolean {
  if (typeof document === 'undefined') return false
  const root = document.documentElement
  return root.getAttribute('data-theme') === 'dark' || root.classList.contains('dark')
}

function processGraphPalette(): ProcessGraphPalette {
  if (isDarkTheme()) {
    return {
      canvasBg: cssVar('--bg', '#0B1224'),
      gridColor: 'rgba(168, 180, 208, 0.16)',
      nodeFill: cssVar('--surface', '#131A2E'),
      nodeText: cssVar('--text', '#E8EEFB'),
      nodeSubText: cssVar('--text-2', '#A8B4D0'),
      endpointStroke: cssVar('--bg', '#0B1224'),
      edgeStroke: 'rgba(168, 180, 208, 0.42)',
      edgeLabelFill: cssVar('--surface', '#131A2E'),
      edgeLabelStroke: cssVar('--line-strong', 'rgba(255, 255, 255, 0.13)'),
      edgeLabelText: cssVar('--text-2', '#A8B4D0'),
      shadowColor: 'rgba(0, 0, 0, 0.42)',
    }
  }
  return {
    canvasBg: cssVar('--surface-2', '#F8FAFC'),
    gridColor: '#e2e8f0',
    nodeFill: '#ffffff',
    nodeText: '#0f172a',
    nodeSubText: '#64748b',
    endpointStroke: '#ffffff',
    edgeStroke: '#cbd5e1',
    edgeLabelFill: '#ffffff',
    edgeLabelStroke: '#e2e8f0',
    edgeLabelText: '#475569',
    shadowColor: 'rgba(15, 23, 42, 0.12)',
  }
}

function buildEdgeAttrs(palette = processGraphPalette()): Record<string, unknown> {
  return {
    line: {
      stroke: palette.edgeStroke,
      strokeWidth: 2,
      targetMarker: { name: 'block', size: 6 },
    },
  }
}

function buildEdgeLabels(text: string, palette = processGraphPalette()): Array<Record<string, unknown>> | undefined {
  if (!text) return undefined
  return [{
    attrs: {
      label: {
        text,
        fill: palette.edgeLabelText,
        fontSize: 11,
        fontWeight: 500,
      },
      body: {
        fill: palette.edgeLabelFill,
        stroke: palette.edgeLabelStroke,
        strokeWidth: 1,
        rx: 4,
        ry: 4,
      },
    },
  }]
}

/** 用 cat code 决定 shape, 用 type/cat 决定 color.
 *  2026-06-08 视觉重做: 实心起止端点 + 白底类别色描边卡片 + 柔和投影,
 *  去掉空心环 / emoji / 浅色平涂的"剪贴画"观感。 */
function buildNodeSpec(type: NodeType, label: string, _icon: string, roleLabel = ''): Record<string, unknown> {
  const cat = getNodeCategoryCode(type)
  const color = getNodeColor(type)
  const meta = cat === 'approval' ? roleLabel.trim() : ''
  const palette = processGraphPalette()
  // x6 内置 dropShadow filter — 给所有节点统一一层柔和投影, 拉开层次感。
  const shadow = { name: 'dropShadow', args: { dx: 0, dy: 3, blur: 8, color: palette.shadowColor } }

  if (cat === 'entry') {
    // 实心圆端点 (start = 绿, end = 红) — 白字白细边 + 阴影, 不再是空心环。
    return {
      shape: 'circle',
      width: 50,
      height: 50,
      label,
      attrs: {
        body: {
          fill: color,
          stroke: palette.endpointStroke,
          strokeWidth: 2,
          filter: shadow,
        },
        label: {
          fill: '#ffffff',
          fontSize: 12,
          fontWeight: 700,
        },
      },
    }
  }

  if (cat === 'logic') {
    // 菱形 (条件分支 / 多分支 / 并行 / 汇聚 / 等待) — 主题底类别色边 + 阴影。
    return {
      shape: 'polygon',
      width: 124,
      height: 68,
      label,
      attrs: {
        body: {
          refPoints: '0,10 10,0 20,10 10,20',
          fill: palette.nodeFill,
          stroke: color,
          strokeWidth: 1.5,
          filter: shadow,
        },
        label: {
          fill: palette.nodeText,
          fontSize: 12,
          fontWeight: 600,
        },
      },
    }
  }

  // approval / action — 圆角卡片 + 类别色描边 + 类别色左侧强调条 + 柔和投影。
  const height = meta ? 66 : 54
  return {
    markup: [
      { tagName: 'rect', selector: 'body' },
      { tagName: 'rect', selector: 'accent' },
      { tagName: 'text', selector: 'label' },
      { tagName: 'text', selector: 'roleLabel' },
    ],
    width: meta ? 184 : 172,
    height,
    label,
    attrs: {
      body: {
        refWidth: '100%',
        refHeight: '100%',
        fill: palette.nodeFill,
        stroke: color,
        strokeWidth: 1.25,
        rx: 13,
        ry: 13,
        filter: shadow,
      },
      accent: {
        x: 0,
        y: meta ? 14 : 12,
        width: 4,
        height: meta ? 38 : 30,
        rx: 2,
        ry: 2,
        fill: color,
      },
      label: {
        refX: 0.5,
        refY: meta ? 0.38 : 0.5,
        text: label,
        fill: palette.nodeText,
        fontSize: 13,
        fontWeight: 600,
        textAnchor: 'middle',
        textVerticalAnchor: 'middle',
      },
      roleLabel: {
        refX: 0.5,
        refY: 0.67,
        text: meta,
        fill: palette.nodeSubText,
        fontSize: 11,
        fontWeight: 500,
        textAnchor: 'middle',
        textVerticalAnchor: 'middle',
      },
    },
  }
}

function refreshCounts(graph: Graph) {
  nodeCount.value = graph.getNodes().length
  edgeCount.value = graph.getEdges().length
}

function clearActiveProcessCanvas() {
  selectedNodeId.value = null
  activeProcessId.value = null
  lastSavedAt.value = null
  lastRenderedDefinition = null
  for (const k of Object.keys(nodeStates)) delete nodeStates[k]
  const graph = graphRef.value
  if (graph) graph.clearCells()
  nodeCount.value = 0
  edgeCount.value = 0
}

function disposeGraph() {
  resizeObserver?.disconnect()
  resizeObserver = null
  graphRef.value?.dispose()
  graphRef.value = null
}

function refreshGraphTheme() {
  const graph = graphRef.value
  if (!graph) return
  const palette = processGraphPalette()
  graph.drawBackground({ color: palette.canvasBg })
  graph.drawGrid({ type: 'dot', args: { color: palette.gridColor, thickness: 1 } })
  if (lastRenderedDefinition) {
    renderDefinition(lastRenderedDefinition.nodes, lastRenderedDefinition.edges, {
      preservePositions: lastRenderedDefinition.preservePositions,
    })
  }
}

function observeThemeChanges() {
  if (typeof MutationObserver === 'undefined' || typeof document === 'undefined') return
  themeObserver?.disconnect()
  themeObserver = new MutationObserver(() => refreshGraphTheme())
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme', 'class'],
  })
}

async function ensureGraphReady() {
  await nextTick()
  if (!graphRef.value && containerRef.value) {
    initGraph()
  }
}

/** 默认 ProcessNode 工厂 — 按 type 注入对应字段默认值. */
function makeDefaultNode(id: string, type: NodeType, label: string): ProcessNode {
  const idx = Object.keys(nodeStates).length + 1
  const base: ProcessNode = {
    id,
    type,
    label,
    key: `n${idx}`,
  }
  if (['assignee_approval', 'role_approval', 'manager_approval', 'parallel_approval', 'cc'].includes(type)) {
    base.approvers = []
    base.strategy = 'single'
    base.slaHours = 24
    base.timeoutAutoApprove = false
    base.allowAddApprover = true
    base.allowReject = true
  } else if (type === 'condition') {
    base.expression = ''
  } else if (type === 'multi_branch') {
    base.branches = []
  } else if (type === 'wait') {
    base.waitMinutes = 60
  } else if (type === 'write_data') {
    base.targetModelCode = ''
    base.fieldMappings = []
  } else if (type === 'read_data') {
    base.sourceModelCode = ''
    base.filterExpression = ''
    base.outputVar = 'result'
  } else if (type === 'timer') {
    base.cron = '0 0 9 * * ?'
    base.description = '每天 9 点'
  } else if (type === 'webhook') {
    base.description = '外部系统回调'
  } else if (type === 'fill_form') {
    base.formCode = ''
    base.assignee = ''
  } else if (type === 'ai_judge' || type === 'ai_generate') {
    base.prompt = ''
    base.outputVar = type === 'ai_judge' ? 'ai_judge_result' : 'ai_text'
    base.model = 'gpt-5.5'
  }
  return base
}

function initGraph() {
  if (!containerRef.value) return
  const palette = processGraphPalette()
  const graph = new Graph({
    container: containerRef.value,
    background: { color: palette.canvasBg },
    grid: {
      visible: true,
      type: 'dot',
      args: { color: palette.gridColor, thickness: 1 },
    },
    panning: { enabled: true, eventTypes: ['leftMouseDown'] },
    mousewheel: { enabled: true, zoomAtMousePosition: true, modifiers: 'ctrl' },
    interacting: { nodeMovable: true },
    connecting: {
      router: 'manhattan',
      connector: { name: 'rounded', args: { radius: 8 } },
      allowBlank: false,
      allowMulti: false,
      allowLoop: false,
      allowNode: false,
      allowEdge: false,
      allowPort: true,
      snap: { radius: 20 },
      createEdge() {
        const edgePalette = processGraphPalette()
        return this.createEdge({
          attrs: buildEdgeAttrs(edgePalette),
        })
      },
    },
  })

  // Selection — sync to right panel
  graph.on('node:click', ({ node }) => {
    selectedNodeId.value = node.id
  })
  graph.on('blank:click', () => {
    selectedNodeId.value = null
  })
  graph.on('node:added', () => refreshCounts(graph))
  graph.on('node:removed', ({ node }) => {
    delete nodeStates[node.id]
    if (selectedNodeId.value === node.id) selectedNodeId.value = null
    refreshCounts(graph)
  })
  graph.on('edge:added', () => refreshCounts(graph))
  graph.on('edge:removed', () => refreshCounts(graph))
  graph.on('node:moved', ({ node }) => {
    const st = nodeStates[node.id]
    if (st) {
      const pos = node.getPosition()
      st.x = pos.x
      st.y = pos.y
    }
  })

  graphRef.value = graph
  refreshCounts(graph)

  // 画布尺寸一变就重新适应(防抖) — 保证流程始终居中并填满当前可用空间。
  if (containerRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver?.disconnect()
    resizeObserver = new ResizeObserver(() => {
      if (refitTimer) clearTimeout(refitTimer)
      refitTimer = setTimeout(() => {
        if (graphRef.value && graphRef.value.getNodes().length) onFitContent()
      }, 160)
    })
    resizeObserver.observe(containerRef.value)
  }
}

/** 空态 "用对话创建流程" CTA — P0 暂时弹示例提示, 后续可 emit 'request-config-chat'
 *  让 ChatPage 把 ConfigAssistant 输入框获焦 + 预填 "为 XX 创建审批流程". */
function onRequestConfigChat() {
  // eslint-disable-next-line no-console
  console.log('[ProcessDesignerPanel] request-config-chat — appId=', props.appId)
  alert('用右下角配置助手对话创建首个审批流程, 比如:\n• "为借书申请加管理员审批流程"\n• "新建报销审批: 部门主管 → 财务复核 → 总经理审批"\n• "为申请单加一个三级审批流"')
}

async function onSelectProcess(processId: string) {
  if (activeProcessId.value === processId) return
  // 切流程: 清当前 canvas state, 准备渲染新流程
  const g = graphRef.value
  clearActiveProcessCanvas()
  activeProcessId.value = processId
  // 默认进 read-only — 切到编辑才能改
  readOnly.value = true
  if (g) {
    ;(g as any).setInteracting(() => ({
      nodeMovable: false,
      edgeMovable: false,
      edgeLabelMovable: false,
      magnetConnectable: false,
      arrowheadMovable: false,
    }))
  }
  // H2: 优先拉本地 ProcessDefinition (前端 H2 简化序列化的产物);
  // 404 → 走 apaas 平台 list 兜底 (G2 老逻辑当前空画布 + 提示 P3 接 detail).
  await tryLoadLocalDefinition(processId)
}

async function reloadProcessList() {
  if (!props.appId) return
  loadingList.value = true
  listError.value = null
  try {
    const resp = await request.get<unknown, {
      ok: boolean
      items?: Array<{ id: string; name: string; code?: string; extra?: Record<string, unknown> }>
      message?: string
      error_code?: string
    }>(`/applications/${props.appId}/section-content/processes`)
    if (resp?.ok) {
      const items = resp.items || []
      processList.value = items.map(it => {
        const raw = (it.extra || {}) as Record<string, unknown>
        return {
          id: it.id,
          name: it.name || '',
          code: it.code || '',
          form_id: typeof raw.form_id === 'string' ? raw.form_id
            : typeof raw.formId === 'string' ? raw.formId
            : typeof raw.bocCode === 'string' ? raw.bocCode
            : undefined,
          status: typeof raw.status === 'string' ? raw.status : undefined,
          extra: raw,
        }
      })
      // 尝试按 form_id 自动选中匹配项 (来自 ChatPage 选菜单的 form_id)
      let autoSelected: string | null = null
      if (props.formId) {
        const match = processList.value.find(p => p.form_id === props.formId)
        if (match) {
          activeProcessId.value = match.id
          autoSelected = match.id
        } else {
          clearActiveProcessCanvas()
        }
      }
      // 没有表单上下文时, 只有 1 个流程才自动选中；有 formId 时不能跨表单兜底。
      if (!props.formId && !activeProcessId.value && processList.value.length === 1) {
        activeProcessId.value = processList.value[0].id
        autoSelected = processList.value[0].id
      }
      // H2: 自动选中后尝试拉本地 definition (graph 可能还没 init, 这里 best-effort —
      // 真正渲染在 onMounted/watch initGraph 完成后, 后续 onSelectProcess 也会再拉.)
      if (autoSelected) {
        // 不 await, 让 list 加载尽快 done
        void tryLoadLocalDefinition(autoSelected)
      }
    } else {
      listError.value = resp?.message || resp?.error_code || '加载失败'
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    listError.value = err?.response?.data?.detail || err?.message || '网络错误'
  } finally {
    loadingList.value = false
  }
}

function onFitContent() {
  const g = graphRef.value
  if (!g) return
  if (g.getNodes().length === 0) return
  g.zoomToFit({ padding: 28, maxScale: 1.5 })
}

/** ProcessDefinition 序列化 — 应用层 JSON (不是 BPMN 2.0 XML).
 * 给 H2 backend `/save-definition` 用的扁平 shape:
 *   { process_name, nodes: [{id, type, label, position, props}], edges: [{id, source, target, label, condition}] }
 */
interface ProcessDefinitionNodeOut {
  id: string
  type: string
  label: string
  position: { x: number; y: number }
  props: Record<string, unknown>
}
interface ProcessDefinitionEdgeOut {
  id: string
  source: string
  target: string
  label?: string
  condition?: string
}
type RenderBox = { x: number; y: number; width: number; height: number; cx: number; cy: number }
type AnchorName = 'top' | 'right' | 'bottom' | 'left' | 'center'
type PositionTransform = { pivotX: number; scaleX: number }
type EdgePoint = { x: number; y: number }

/** 自动布局 — 按入度拓扑分层 (BFS) + 每层水平居中铺开, 返回 nodeId → {x,y}. */
function computeAutoLayout(
  nodes: { id: string }[],
  edges: { source: string; target: string }[],
): Map<string, { x: number; y: number }> {
  const TOP = 40, VGAP = 96, HGAP = 200, CENTER = 320
  const ids = nodes.map(n => n.id)
  const idset = new Set(ids)
  const incoming = new Map<string, number>(ids.map(id => [id, 0]))
  const adj = new Map<string, string[]>(ids.map(id => [id, []]))
  for (const e of edges) {
    if (idset.has(e.source) && idset.has(e.target)) {
      adj.get(e.source)!.push(e.target)
      incoming.set(e.target, (incoming.get(e.target) || 0) + 1)
    }
  }
  let roots = ids.filter(id => (incoming.get(id) || 0) === 0)
  if (!roots.length && ids.length) roots = [ids[0]]
  const level = new Map<string, number>(roots.map(r => [r, 0]))
  const queue = [...roots]
  while (queue.length) {
    const u = queue.shift()!
    const lu = level.get(u) || 0
    for (const v of adj.get(u) || []) {
      const nl = lu + 1
      if (!level.has(v) || nl > (level.get(v) || 0)) { level.set(v, nl); queue.push(v) }
    }
  }
  // 未被任何边连到的孤立节点 → 依次排到最底下, 不挤在一起
  let maxL = 0; level.forEach(l => { if (l > maxL) maxL = l })
  for (const id of ids) if (!level.has(id)) { maxL += 1; level.set(id, maxL) }
  const byLevel = new Map<number, string[]>()
  for (const id of ids) {
    const l = level.get(id) || 0
    if (!byLevel.has(l)) byLevel.set(l, [])
    byLevel.get(l)!.push(id)
  }
  const pos = new Map<string, { x: number; y: number }>()
  for (const [l, group] of byLevel) {
    const n = group.length
    group.forEach((id, i) => {
      pos.set(id, { x: CENTER + (i - (n - 1) / 2) * HGAP, y: TOP + l * VGAP })
    })
  }
  return pos
}

function hasMeaningfulSourcePositions(nodes: ProcessDefinitionNodeOut[]): boolean {
  return nodes.some(n => {
    const x = Number(n.position?.x)
    const y = Number(n.position?.y)
    return Number.isFinite(x) && Number.isFinite(y) && (Math.abs(x) > 0.1 || Math.abs(y) > 0.1)
  })
}

function estimateNodeWidth(node: ProcessDefinitionNodeOut): number {
  const type = node.type as NodeType
  const cat = getNodeCategoryCode(type)
  if (cat === 'entry') return 50
  if (cat === 'logic') return 124
  return getNodeCategoryCode(type) === 'approval' && processApproverDisplay(node.props) ? 184 : 172
}

function computeSourcePositionTransform(nodes: ProcessDefinitionNodeOut[]): PositionTransform {
  const roundedBuckets = new Map<number, number>()
  for (const node of nodes) {
    const x = Number(node.position?.x)
    if (!Number.isFinite(x)) continue
    const bucket = Math.round(x / 8) * 8
    roundedBuckets.set(bucket, (roundedBuckets.get(bucket) || 0) + 1)
  }
  let pivotX = 320
  let maxCount = 0
  for (const [bucket, count] of roundedBuckets) {
    if (count > maxCount) {
      maxCount = count
      pivotX = bucket
    }
  }

  const ROW_TOLERANCE = 28
  const MIN_GAP = 24
  let scaleX = 1
  const sortedByY = [...nodes]
    .filter(n => Number.isFinite(Number(n.position?.x)) && Number.isFinite(Number(n.position?.y)))
    .sort((a, b) => Number(a.position.y) - Number(b.position.y))
  const rows: ProcessDefinitionNodeOut[][] = []
  for (const node of sortedByY) {
    const row = rows.find(items => Math.abs(Number(items[0].position.y) - Number(node.position.y)) <= ROW_TOLERANCE)
    if (row) row.push(node)
    else rows.push([node])
  }
  for (const row of rows) {
    if (row.length < 2) continue
    const items = [...row].sort((a, b) => Number(a.position.x) - Number(b.position.x))
    for (let i = 1; i < items.length; i += 1) {
      const prev = items[i - 1]
      const curr = items[i]
      const prevCenter = Number(prev.position.x) + estimateNodeWidth(prev) / 2
      const currCenter = Number(curr.position.x) + estimateNodeWidth(curr) / 2
      const distance = currCenter - prevCenter
      const needed = (estimateNodeWidth(prev) + estimateNodeWidth(curr)) / 2 + MIN_GAP
      if (distance > 0 && distance < needed) {
        scaleX = Math.max(scaleX, needed / distance)
      }
    }
  }

  return { pivotX, scaleX: Math.min(scaleX, 1.8) }
}

function transformSourcePosition(position: { x: number; y: number }, transform: PositionTransform): { x: number; y: number } {
  return {
    x: transform.pivotX + (position.x - transform.pivotX) * transform.scaleX,
    y: position.y,
  }
}

function chooseEdgeAnchors(edge: ProcessDefinitionEdgeOut, boxes: Map<string, RenderBox>): {
  source: { cell: string; anchor: { name: AnchorName } }
  target: { cell: string; anchor: { name: AnchorName } }
} {
  const sourceBox = boxes.get(edge.source)
  const targetBox = boxes.get(edge.target)
  if (!sourceBox || !targetBox) {
    return {
      source: { cell: edge.source, anchor: { name: 'center' } },
      target: { cell: edge.target, anchor: { name: 'center' } },
    }
  }

  const dx = targetBox.cx - sourceBox.cx
  const dy = targetBox.cy - sourceBox.cy
  if (Math.abs(dy) <= Math.max(sourceBox.height, targetBox.height) * 0.45) {
    return dx >= 0
      ? {
          source: { cell: edge.source, anchor: { name: 'right' } },
          target: { cell: edge.target, anchor: { name: 'left' } },
        }
      : {
          source: { cell: edge.source, anchor: { name: 'left' } },
          target: { cell: edge.target, anchor: { name: 'right' } },
        }
  }

  return dy >= 0
    ? {
        source: { cell: edge.source, anchor: { name: 'bottom' } },
        target: { cell: edge.target, anchor: { name: 'top' } },
      }
    : {
        source: { cell: edge.source, anchor: { name: 'top' } },
        target: { cell: edge.target, anchor: { name: 'bottom' } },
      }
}

function buildPointEdgeConnection(edge: ProcessDefinitionEdgeOut, boxes: Map<string, RenderBox>): {
  source: EdgePoint
  target: EdgePoint
  vertices?: EdgePoint[]
} | null {
  const sourceBox = boxes.get(edge.source)
  const targetBox = boxes.get(edge.target)
  if (!sourceBox || !targetBox) return null

  const dx = targetBox.cx - sourceBox.cx
  const dy = targetBox.cy - sourceBox.cy
  if (Math.abs(dy) <= Math.max(sourceBox.height, targetBox.height) * 0.45) {
    return dx >= 0
      ? {
          source: { x: sourceBox.x + sourceBox.width, y: sourceBox.cy },
          target: { x: targetBox.x, y: targetBox.cy },
        }
      : {
          source: { x: sourceBox.x, y: sourceBox.cy },
          target: { x: targetBox.x + targetBox.width, y: targetBox.cy },
        }
  }

  const source = dy >= 0
    ? { x: sourceBox.cx, y: sourceBox.y + sourceBox.height }
    : { x: sourceBox.cx, y: sourceBox.y }
  const target = dy >= 0
    ? { x: targetBox.cx, y: targetBox.y }
    : { x: targetBox.cx, y: targetBox.y + targetBox.height }
  const vertices = Math.abs(dx) > 24
    ? [
        { x: source.x, y: source.y + (target.y - source.y) / 2 },
        { x: target.x, y: source.y + (target.y - source.y) / 2 },
      ]
    : undefined
  return { source, target, vertices }
}

/** H2: 渲染本地 ProcessDefinition (从 GET /definition 拿到的 nodes/edges) 到 x6. */
function renderDefinition(
  defNodes: ProcessDefinitionNodeOut[],
  defEdges: ProcessDefinitionEdgeOut[],
  options: { preservePositions?: boolean } = {},
) {
  const g = graphRef.value
  if (!g) return
  const palette = processGraphPalette()
  const preservePositions = options.preservePositions === true && hasMeaningfulSourcePositions(defNodes)
  lastRenderedDefinition = { nodes: defNodes, edges: defEdges, preservePositions }
  g.clearCells()
  for (const k of Object.keys(nodeStates)) delete nodeStates[k]
  // aPaaS 详情自带设计器坐标；分支流必须保留平台坐标，否则拓扑自动布局会把侧向分支排进主链。
  // 本地旧 definition 没有可信坐标时，仍回退到拓扑自动布局。
  const layout = preservePositions ? new Map<string, { x: number; y: number }>() : computeAutoLayout(defNodes, defEdges)
  const sourceTransform = preservePositions ? computeSourcePositionTransform(defNodes) : null
  const renderBoxes = new Map<string, RenderBox>()
  // 节点
  for (const n of defNodes) {
    const type = n.type as NodeType
    const def = getNodeDef(type)
    if (!def) {
      // 未知 type — 跳过, 不挡其他节点渲染
      continue
    }
    const roleLabel = getNodeCategoryCode(type) === 'approval' ? processApproverDisplay(n.props) : ''
    const spec = buildNodeSpec(type, n.label || def.label, def.icon, roleLabel)
    const p = preservePositions
      ? transformSourcePosition(n.position || { x: 100, y: 100 }, sourceTransform!)
      : (layout.get(n.id) || n.position || { x: 100, y: 100 })
    // 居中对齐: 布局给的是该层「中心 x」, 但 x6 按左上角定位、各节点宽度不同
    // (开始/结束 50px 圆 vs 审批卡片 172px)。若都左对齐到同一 x, 节点中心就错开了,
    // 连线只能斜着连 → 弯弯绕绕。减去半宽让各节点「中心」对齐, 连线即拉直。
    const w = typeof spec.width === 'number' ? spec.width : 140
    const h = typeof spec.height === 'number' ? spec.height : 54
    const nodeX = preservePositions ? p.x : p.x - w / 2
    const nodeY = p.y
    g.addNode({
      id: n.id,
      x: nodeX,
      y: nodeY,
      ...spec,
      data: { type, color: getNodeColor(type) },
    } as never)
    renderBoxes.set(n.id, {
      x: nodeX,
      y: nodeY,
      width: w,
      height: h,
      cx: nodeX + w / 2,
      cy: nodeY + h / 2,
    })
    const st = makeDefaultNode(n.id, type, n.label || def.label)
    st.x = p.x
    st.y = p.y
    // 把 props 合回 nodeStates (覆盖默认值)
    if (n.props && typeof n.props === 'object') {
      for (const [k, v] of Object.entries(n.props)) {
        ;(st as unknown as Record<string, unknown>)[k] = v
      }
    }
    nodeStates[n.id] = st
  }
  // 边
  for (const e of defEdges) {
    try {
      const edgeLabel = e.label || e.condition || ''
      const pointConnection = preservePositions ? buildPointEdgeConnection(e, renderBoxes) : null
      const terminals = pointConnection ? null : chooseEdgeAnchors(e, renderBoxes)
      g.addEdge({
        id: e.id,
        source: pointConnection?.source || terminals!.source,
        target: pointConnection?.target || terminals!.target,
        vertices: pointConnection?.vertices,
        labels: buildEdgeLabels(edgeLabel, palette),
        data: e.condition ? { condition: e.condition } : undefined,
        attrs: buildEdgeAttrs(palette),
        router: { name: 'normal' },
        connector: { name: 'normal' },
      } as never)
    } catch {
      // ignore bad edge
    }
  }
  refreshCounts(g)
  // 渲染后自动适应视口, 免得图渲在视口外要手点「适应」
  if (readOnly.value) {
    void nextTick(() => onFitContent())
  }
}

/** H2: 尝试从 backend 拉本地 ProcessDefinition; 404 → 走 J1 apaas detail 兜底. */
async function tryLoadLocalDefinition(processId: string): Promise<boolean> {
  if (!props.appId || !processId) return false
  try {
    const resp = await request.get<unknown, {
      ok: boolean
      nodes?: ProcessDefinitionNodeOut[]
      edges?: ProcessDefinitionEdgeOut[]
      updated_at?: string
    }>(`/applications/${props.appId}/processes/${processId}/definition`)
    if (resp?.ok && (Array.isArray(resp.nodes) || Array.isArray(resp.edges)) && ((resp.nodes?.length || 0) + (resp.edges?.length || 0) > 0)) {
      await nextTick()
      renderDefinition(resp.nodes || [], resp.edges || [])
      lastSavedAt.value = resp.updated_at || null
      return true
    }
    // 空 definition — 走 J1 apaas 兜底
  } catch (e: unknown) {
    const err = e as { response?: { status?: number } }
    if (err?.response?.status !== 404) {
      // 非 404 是真错 — 但不阻塞 apaas 兜底
    }
  }
  // J1 兜底: 拉 apaas 平台已有定义
  return await tryLoadApaasDetail(processId)
}

/** J1: 本地 definition 没有时, 拉 apaas 平台真有的流程详情. */
async function tryLoadApaasDetail(processId: string): Promise<boolean> {
  if (!props.appId || !processId) return false
  try {
    const resp = await request.get<unknown, {
      ok: boolean
      nodes?: ProcessDefinitionNodeOut[]
      edges?: ProcessDefinitionEdgeOut[]
      source?: string
    }>(`/applications/${props.appId}/processes/${processId}/apaas-detail`)
    if (resp?.ok && (Array.isArray(resp.nodes) || Array.isArray(resp.edges)) && ((resp.nodes?.length || 0) + (resp.edges?.length || 0) > 0)) {
      await nextTick()
      renderDefinition(resp.nodes || [], resp.edges || [], { preservePositions: resp.source === 'apaas_process_detail' })
      return true
    }
    return false
  } catch (e: unknown) {
    const err = e as { response?: { status?: number, data?: { detail?: string } } }
    if (err?.response?.status === 404) {
      // apaas 也没有 — 空画布, 显友好提示
      return false
    }
    return false
  }
}

onMounted(async () => {
  observeThemeChanges()
  await reloadProcessList()
  // 当前表单有可见流程时才初始化画布；否则保持空态, 不渲染别的表单流程。
  if (visibleProcessList.value.length > 0) {
    await ensureGraphReady()
  }
})

onBeforeUnmount(() => {
  if (refitTimer) { clearTimeout(refitTimer); refitTimer = null }
  themeObserver?.disconnect()
  themeObserver = null
  disposeGraph()
})

watch(
  () => props.appId,
  async (next, prev) => {
    if (next === prev) return
    // 应用切了: 清 graph + state, 重新拉 list
    disposeGraph()
    selectedNodeId.value = null
    activeProcessId.value = null
    for (const k of Object.keys(nodeStates)) delete nodeStates[k]
    nodeCount.value = 0
    edgeCount.value = 0
    processList.value = []
    await reloadProcessList()
    if (visibleProcessList.value.length > 0) {
      await ensureGraphReady()
    }
  },
)

watch(
  () => props.formId,
  async (next, prev) => {
    if (next === prev) return
    if (!processList.value.length) return

    const match = next
      ? processList.value.find(p => p.form_id === next)
      : null
    if (!match) {
      clearActiveProcessCanvas()
      disposeGraph()
      return
    }

    await ensureGraphReady()
    await onSelectProcess(match.id)
  },
)

// 一旦当前表单可见流程从 0 → N, 触发 initGraph (template 才有 containerRef)
watch(
  () => visibleProcessList.value.length,
  async (next, prev) => {
    if (next > 0 && prev === 0 && !graphRef.value) {
      await ensureGraphReady()
    }
  },
)
</script>

<style scoped>
.pdp {
  font-family: var(--font-sans);
  color: var(--text);
  background: var(--bg);
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-feature-settings: 'cv11', 'ss01';
}

.pdp-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-3);
  gap: 12px;
}
.pdp-empty-icon { font-size: 48px; line-height: 1; }
.pdp-empty h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.pdp-empty p {
  margin: 0;
  font-size: 13.5px;
}
/* 空态主 CTA — design-v3 token, 跟周围保持一致 */
.pdp-empty-process {
  padding: 32px 24px;
  max-width: 480px;
  margin: 0 auto;
}
.pdp-empty-process .pdp-empty-icon {
  font-size: 56px;
  opacity: 0.9;
}
.pdp-empty-process h3 {
  margin-top: 4px;
  letter-spacing: -0.3px;
}
.pdp-empty-process p {
  color: var(--text-3);
  line-height: 1.55;
  max-width: 380px;
}
.pdp-empty-cta {
  margin-top: 8px;
  height: 36px;
  padding: 0 18px;
  font-size: 13px;
  gap: 6px;
}

/* ───── 顶部 toolbar ───── */
.pdp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 28px 16px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
  background: var(--surface);
}
.pdp-title {
  margin: 0 0 6px;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.3px;
}
.pdp-sub {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--text-3);
}
.pdp-stat {
  font-size: 12.5px;
  color: var(--text-3);
}

.pdp-head-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.pdp-btn {
  height: 32px;
  padding: 0 14px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid transparent;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.pdp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.pdp-btn-ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--text-2);
}
.pdp-btn-ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.pdp-btn-primary {
  background: var(--brand);
  color: #fff;
}
.pdp-btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
}

/* ───── 主区: 左 sidebar + 中央 canvas + 右属性 ───── */
.pdp-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

/* ───── 左 sidebar: 节点库 collapsible 分类 ───── */
.pdp-sidebar {
  width: 240px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--line);
  padding: 16px 12px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.pdp-sidebar-title {
  margin: 8px 4px 12px;
  font-size: 11.5px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  color: var(--text-4);
}

/* ───── 流程列表 panel ───── */
.pdp-section {
  display: flex;
  flex-direction: column;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
}
.pdp-section-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
  text-align: left;
  border-radius: 4px;
  transition: background 0.12s;
}
.pdp-section-head:hover {
  background: var(--surface-2);
}
.pdp-process-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px 4px 4px;
  max-height: 200px;
  overflow-y: auto;
}
.pdp-process-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--text-2);
  text-align: left;
  transition: background 0.12s, border-color 0.12s;
  overflow: hidden;
}
.pdp-process-item:hover {
  border-color: var(--brand);
  background: var(--brand-soft);
}
.pdp-process-item.is-active {
  border-color: var(--brand);
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 500;
}
.pdp-process-icon {
  font-size: 14px;
  flex-shrink: 0;
}
.pdp-process-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pdp-cat-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pdp-cat {
  display: flex;
  flex-direction: column;
}
.pdp-cat-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
  text-align: left;
  border-radius: 4px;
  transition: background 0.12s;
}
.pdp-cat-head:hover {
  background: var(--surface-2);
}
.pdp-cat-arrow {
  font-size: 9px;
  color: var(--text-4);
  display: inline-block;
  transition: transform 0.15s var(--ease);
}
.pdp-cat-arrow.is-open {
  transform: rotate(90deg);
}
.pdp-cat-label {
  flex: 1;
}
.pdp-cat-count {
  font-size: 11px;
  color: var(--text-4);
  font-weight: 400;
}

.pdp-chip-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  padding: 6px 4px 8px;
}
.pdp-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 6px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.12s, border-color 0.12s, transform 0.12s;
}
.pdp-chip:hover:not(:disabled) {
  border-color: var(--brand);
  background: var(--brand-soft);
  transform: translateY(-1px);
}
.pdp-chip:active:not(:disabled) {
  transform: translateY(0);
}
.pdp-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.pdp-chip-icon {
  font-size: 18px;
  line-height: 1;
}
.pdp-chip-label {
  font-size: 11.5px;
  color: var(--text-2);
  text-align: center;
  line-height: 1.3;
}
/* Category-tinted chip hover by data-cat */
.pdp-chip[data-cat="entry"]:hover    { border-color: var(--ok);    background: var(--ok-soft); }
.pdp-chip[data-cat="approval"]:hover { border-color: var(--brand); background: var(--brand-soft); }
.pdp-chip[data-cat="logic"]:hover    { border-color: var(--warn);  background: var(--warn-soft); }
.pdp-chip[data-cat="action"]:hover   { border-color: var(--info);  background: var(--info-soft); }

.pdp-sidebar-foot {
  margin: 12px 4px 4px;
  font-size: 11.5px;
  color: var(--text-4);
  line-height: 1.5;
}

/* ───── 中央 canvas ───── */
.pdp-canvas-wrap {
  flex: 1;
  min-width: 0;
  background: var(--surface-2);
  position: relative;
}
.pdp-canvas {
  width: 100%;
  height: 100%;
  position: absolute;
  inset: 0;
}
.pdp-canvas-hint {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  pointer-events: none;
  color: var(--text-4);
  text-align: center;
  font-size: 13px;
}
.pdp-canvas-hint-icon {
  font-size: 48px;
  line-height: 1;
  color: var(--text-4);
  margin-bottom: 8px;
  opacity: 0.6;
}
.pdp-canvas-hint p {
  margin: 0;
}
.pdp-canvas-hint-sub {
  display: inline-block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-4);
  max-width: 360px;
  line-height: 1.55;
}

/* ─── view mode sidebar 占位文案 ─── */
.pdp-sidebar-foot-view {
  margin-top: 12px;
  padding: 12px;
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.55;
  text-align: center;
}

</style>

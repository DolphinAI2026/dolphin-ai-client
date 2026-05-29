<!-- ProcessDesignerPanel.vue — Native 流程设计器面板 (替 apaas process designer iframe).

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
      <div class="pdp-empty-icon">⏳</div>
      <h3>加载流程列表...</h3>
    </div>

    <!-- 拉 list 出错 (应用未部署 / token 失效) -->
    <div v-else-if="listError" class="pdp-empty">
      <div class="pdp-empty-icon">⚠️</div>
      <h3>加载失败</h3>
      <p>{{ listError }}</p>
      <button class="pdp-btn pdp-btn-ghost" @click="reloadProcessList">重试</button>
    </div>

    <!-- 应用无流程 — 友好空态 + 引导对话 CTA.
         注: 区别于 `pdp-canvas-hint` ("「X」尚无流程定义" 那个) — 那个是选中流程但定义空,
         这里是整个应用一个流程都没有 (例如 app_id=13 图书借阅管理系统). -->
    <div v-else-if="processList.length === 0" class="pdp-empty pdp-empty-process">
      <div class="pdp-empty-icon" aria-hidden="true">🔀</div>
      <h3>暂无业务流程</h3>
      <p>用配置助手对话生成首个审批流, 例如：「为借书申请加管理员审批流程」</p>
      <button
        type="button"
        class="pdp-btn pdp-btn-primary pdp-empty-cta"
        @click="onRequestConfigChat"
      >
        <span aria-hidden="true">✨</span>
        用对话创建流程
      </button>
    </div>

    <!-- 有流程: 显完整设计器 -->
    <template v-else>
      <!-- O2: 业务视角 banner (仅 view mode 显) -->
      <div v-if="readOnly && activeProcess" class="pdp-biz-banner" role="status">
        <span class="pdp-biz-banner-icon">✨</span>
        <span class="pdp-biz-banner-text">
          业务视角预览 — 申请单 <strong>{{ mockInstance.instanceCode }}</strong>
          提交于 <strong>{{ mockInstance.submittedAgo }}</strong>,
          当前等待 <strong>[{{ mockInstance.currentApprover }}]</strong> 审批.
        </span>
      </div>

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
          <!-- O2: segmented control 业务 / 设计 -->
          <div class="pdp-mode-segment" role="tablist" aria-label="视角切换">
            <button
              class="pdp-mode-segment-btn"
              :class="{ 'is-active': readOnly }"
              role="tab"
              :aria-selected="readOnly"
              @click="setViewMode(true)"
              title="业务视角 — 看实例进度"
            >👁 业务</button>
            <button
              class="pdp-mode-segment-btn"
              :class="{ 'is-active': !readOnly }"
              role="tab"
              :aria-selected="!readOnly"
              @click="setViewMode(false)"
              title="设计视角 — 加节点 / 连线 / 保存"
            >✏️ 设计</button>
          </div>
          <!-- 适应画布 仅业务视角 (设计模式 center 是 apaas iframe, 原生 canvas 隐藏) -->
          <button v-if="readOnly" class="pdp-btn pdp-btn-ghost" @click="onFitContent" title="适应画布">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7V3h4M21 7V3h-4M3 17v4h4M21 17v4h-4"/></svg>
            适应
          </button>
        </div>
      </header>

      <div class="pdp-body">
        <!-- 左 sidebar: 流程列表 (始终显) + 模式提示 -->
        <aside class="pdp-sidebar" aria-label="流程列表">
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
                <span class="pdp-process-icon">🔀</span>
                <span class="pdp-process-name">{{ p.name || p.code || p.id }}</span>
              </button>
            </div>
          </div>

          <!-- ── 设计模式: 提示走右侧 apaas 原生编辑器 (节点库 / 连线 / 审批人配置都在 iframe 里) ── -->
          <p v-if="!readOnly" class="pdp-sidebar-foot pdp-sidebar-foot-view">
            ✏️ 设计模式 — 在右侧 apaas 原生流程编辑器加节点 / 连线 / 配置审批人, 或用 ✨ 对话改流程
          </p>
          <!-- view mode: 占位提示 — 切到设计可改流程 -->
          <p v-else class="pdp-sidebar-foot pdp-sidebar-foot-view">
            👁 业务视角 — 切到 ✏️ 设计模式后才能改流程
          </p>
        </aside>

        <!-- 中央 x6 canvas — 业务视角原生只读视图.
             用 v-show (非 v-if) 保持 containerRef 始终在 DOM, 切到设计模式不销毁 x6 graph 实例
             (设计模式 center 改 apaas iframe, canvas 仅 display:none). -->
        <div v-show="readOnly" class="pdp-canvas-wrap">
          <div ref="containerRef" class="pdp-canvas"></div>
          <div v-if="!nodeCount && activeProcess" class="pdp-canvas-hint">
            <div class="pdp-canvas-hint-icon">⊕</div>
            <p>
              <strong>"{{ activeProcess.name || activeProcess.code }}"</strong> 尚无流程定义
              <br />
              <span class="pdp-canvas-hint-sub">
                切到 ✏️ 设计模式用 apaas 原生编辑器搭建流程, 或用配置助手对话快速生成
              </span>
            </p>
          </div>
          <div v-if="!activeProcess" class="pdp-canvas-hint">
            <div class="pdp-canvas-hint-icon">👈</div>
            <p>从左侧"流程列表"选择一个流程</p>
          </div>
        </div>

        <!-- 设计模式 center — apaas 原生流程编辑器 iframe (designer-sub=process → 自动激活 tab-workFlowDesign).
             menu-id 用 props.menuId; form-id 优先当前选中流程的 form_id, 兜底 props.formId. -->
        <ApaasEmbedIframe
          v-if="!readOnly"
          class="pdp-iframe"
          :app-id="props.appId"
          :menu-id="props.menuId || ''"
          :form-id="activeProcess?.form_id || props.formId || null"
          menu-type="MODEL"
          mode="config"
          designer-sub="process"
        />

        <!-- O2: 右 — view mode 显历史轨迹时间轴; edit mode 显节点属性面板 -->
        <aside v-if="readOnly && activeProcess" class="pdp-timeline" aria-label="历史轨迹">
          <header class="pdp-timeline-head">
            <h3 class="pdp-timeline-title">进度时间轴</h3>
            <p class="pdp-timeline-sub">{{ mockInstance.instanceCode }} · 已 {{ mockInstance.submittedAgo }}</p>
          </header>
          <ol class="pdp-timeline-list">
            <li
              v-for="item in timelineItems"
              :key="item.nodeId"
              class="pdp-timeline-item"
              :class="['is-' + item.status]"
            >
              <span class="pdp-timeline-dot" :class="['is-' + item.status]">
                <span v-if="item.status === 'completed'">✓</span>
                <span v-else-if="item.status === 'current'">◉</span>
                <span v-else>○</span>
              </span>
              <div class="pdp-timeline-body">
                <div class="pdp-timeline-row">
                  <span class="pdp-timeline-name">{{ item.label }}</span>
                  <span v-if="item.status === 'current'" class="pdp-timeline-tag">← 当前</span>
                </div>
                <p class="pdp-timeline-meta">
                  <template v-if="item.status === 'completed'">
                    by {{ item.by }} · {{ item.at }}
                  </template>
                  <template v-else-if="item.status === 'current'">
                    等待 <strong>{{ item.by }}</strong>
                  </template>
                  <template v-else>
                    未开始
                  </template>
                </p>
              </div>
            </li>
          </ol>
        </aside>

        <ProcessNodePropsPanel
          v-else-if="!readOnly && selectedNode"
          :node="selectedNode"
          :model-options="modelOptions"
          @change="onPropsChange"
          @close="clearSelection"
          @ai-query="onAiQuery"
        />
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, shallowRef, reactive, nextTick } from 'vue'
import { Graph, type Node as X6Node, type Edge as X6Edge } from '@antv/x6'
import { ElMessage } from 'element-plus'
import ProcessNodePropsPanel from './ProcessNodePropsPanel.vue'
import ApaasEmbedIframe from './ApaasEmbedIframe.vue'
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
}>()

const containerRef = ref<HTMLElement | null>(null)
const graphRef = shallowRef<Graph | null>(null)

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
const saving = ref(false)
const lastSavedAt = ref<string | null>(null)

/** I4: 部署到 apaas 平台 loading + 上次同步时间/版本. */
const deploying = ref(false)
const lastDeployedAt = ref<string | null>(null)
const lastDeployedVersion = ref<number | null>(null)

/** O2: 业务视角 — mock 流程实例 (P2 接真 apaas runtime API 才有).
 *  完整状态: completedNodes (已通过) / currentNodeId (当前) / pendingNodes (未到).
 *  history: 已完成节点的审批轨迹 (谁审 / 何时).
 */
type NodeProgressStatus = 'completed' | 'current' | 'pending'
interface MockHistoryEntry {
  nodeId: string
  action: string
  by: string
  at: string
}
interface MockInstanceState {
  instanceCode: string
  submittedAgo: string
  currentNodeId: string | null
  currentApprover: string
  completedNodes: string[]
  pendingNodes: string[]
  startedAt: string
  history: MockHistoryEntry[]
}
const mockInstance = ref<MockInstanceState>({
  instanceCode: 'SQDH-2026-001',
  submittedAgo: '3 分钟前',
  currentNodeId: null,
  currentApprover: '张三',
  completedNodes: [],
  pendingNodes: [],
  startedAt: new Date(Date.now() - 3 * 60_000).toISOString(),
  history: [],
})

/** mock 假名池 — calcMockInstanceProgress 给每个节点分配审批人. */
const MOCK_APPROVERS = ['张三', '李四', '王五', '赵六', '孙七', '周八']
const MOCK_ACTIONS = ['提交申请', '审批通过', '审批通过', '审批通过', '审批通过']

const activeProcess = computed<ProcessItem | null>(() => {
  if (!activeProcessId.value) return null
  return processList.value.find(p => p.id === activeProcessId.value) || null
})

// 2026-05-28: 流程列表只显示"当前表单/菜单"的流程 (用户反馈别把全应用流程都列出来)。
// props.formId 在时按 form_id 过滤; 过滤后为空 (数据不一致) 则兜底显示全部, 避免一个都看不到。
const visibleProcessList = computed<ProcessItem[]>(() => {
  const fid = props.formId
  if (!fid) return processList.value
  const matched = processList.value.filter(p => p.form_id === fid)
  return matched.length ? matched : processList.value
})

const selectedNode = computed<ProcessNode | null>(() => {
  if (!selectedNodeId.value) return null
  return nodeStates[selectedNodeId.value] || null
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

/** 待 P2 接 list_apaas_app_models — 当前用 placeholder. */
const modelOptions = computed(() => [
  { code: 'apply_form', label: '申请表 (apply_form)' },
  { code: 'approval_log', label: '审批日志 (approval_log)' },
])

/** O2: 历史轨迹 timeline 数据 — 按 graph 节点拓扑顺序 (简化 = nodeStates 插入序) +
 *  按 mockInstance 三段状态分类.
 */
interface TimelineItem {
  nodeId: string
  label: string
  status: NodeProgressStatus
  by: string
  at: string
}
const timelineItems = computed<TimelineItem[]>(() => {
  const items: TimelineItem[] = []
  const m = mockInstance.value
  const order = orderedNodeIds()
  for (const id of order) {
    const st = nodeStates[id]
    if (!st) continue
    let status: NodeProgressStatus = 'pending'
    if (m.completedNodes.includes(id)) status = 'completed'
    else if (m.currentNodeId === id) status = 'current'
    // 找 history entry
    const hist = m.history.find(h => h.nodeId === id)
    const label = st.label || st.type
    items.push({
      nodeId: id,
      label,
      status,
      by: hist?.by || (status === 'current' ? m.currentApprover : ''),
      at: hist?.at || '',
    })
  }
  return items
})

/** Order nodes for timeline — 用 entry → end 拓扑 (best-effort)
 *  简化: 取 nodeStates 插入顺序; 后续 P2 可改 edges BFS.
 */
function orderedNodeIds(): string[] {
  return Object.keys(nodeStates)
}

/** 用 cat code 决定 shape, 用 type/cat 决定 color. */
function buildNodeSpec(type: NodeType, label: string, icon: string): Record<string, unknown> {
  const cat = getNodeCategoryCode(type)
  const color = getNodeColor(type)
  const displayLabel = `${icon}  ${label}`

  if (cat === 'entry') {
    // 圆形 (start = 绿, end = 红, timer/webhook = entry 默认绿)
    return {
      shape: 'circle',
      width: 64,
      height: 64,
      label: displayLabel,
      attrs: {
        body: {
          fill: '#ffffff',
          stroke: color,
          strokeWidth: 2.5,
        },
        label: {
          fill: color,
          fontSize: 11,
          fontWeight: 600,
        },
      },
    }
  }

  if (cat === 'logic') {
    // 菱形 (条件分支 / 多分支 / 并行 / 汇聚 / 等待)
    return {
      shape: 'polygon',
      width: 110,
      height: 70,
      label: displayLabel,
      attrs: {
        body: {
          refPoints: '0,10 10,0 20,10 10,20',
          fill: '#fffbeb',
          stroke: color,
          strokeWidth: 2,
        },
        label: {
          fill: '#92400e',
          fontSize: 11.5,
          fontWeight: 500,
        },
      },
    }
  }

  if (cat === 'action') {
    // 矩形 (动作类) — 紫色边
    return {
      shape: 'rect',
      width: 140,
      height: 50,
      label: displayLabel,
      attrs: {
        body: {
          fill: '#faf5ff',
          stroke: color,
          strokeWidth: 1.5,
          rx: 4,
          ry: 4,
        },
        label: {
          fill: '#5b21b6',
          fontSize: 12,
          fontWeight: 500,
        },
      },
    }
  }

  // approval — 圆角矩形 (蓝色边)
  return {
    shape: 'rect',
    width: 140,
    height: 56,
    label: displayLabel,
    attrs: {
      body: {
        fill: '#eff6ff',
        stroke: color,
        strokeWidth: 1.5,
        rx: 10,
        ry: 10,
      },
      label: {
        fill: '#1e40af',
        fontSize: 12.5,
        fontWeight: 500,
      },
    },
  }
}

function refreshCounts(graph: Graph) {
  nodeCount.value = graph.getNodes().length
  edgeCount.value = graph.getEdges().length
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
  const graph = new Graph({
    container: containerRef.value,
    background: { color: '#f8fafc' },
    grid: {
      visible: true,
      type: 'dot',
      args: { color: '#e2e8f0', thickness: 1 },
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
        return this.createEdge({
          attrs: {
            line: {
              stroke: '#94a3b8',
              strokeWidth: 1.5,
              targetMarker: { name: 'classic', size: 7 },
            },
          },
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
}

/** O2: 显式设视角 — 业务 (read=true) / 设计 (read=false). 自动同步 x6 interacting + 重绘 mock 进度. */
function setViewMode(viewMode: boolean) {
  if (!activeProcess.value) {
    // 允许切但不弹错 — 业务视角即使没流程也无害
    readOnly.value = viewMode
    return
  }
  readOnly.value = viewMode
  const g = graphRef.value
  if (g) {
    g.setInteracting(() => (viewMode
      ? { nodeMovable: false, edgeMovable: false, edgeLabelMovable: false, magnetConnectable: false, arrowheadMovable: false }
      : { nodeMovable: true }
    ))
  }
  // 切到业务视角时重新画一次 mock 进度 (edit 改了节点也能看到最新进度)
  if (viewMode) {
    paintInstanceProgress()
  } else {
    // 切到设计 — center 改 apaas iframe, 原生 canvas 隐藏.
    // 清原生节点选中 (否则切换后 ProcessNodePropsPanel 会跟 iframe 同时渲染).
    selectedNodeId.value = null
    // 还原默认节点 stroke 颜色 (清 mock 状态视觉, 切回业务视角时干净)
    clearInstanceProgress()
  }
}

/** 空态 "用对话创建流程" CTA — P0 暂时弹示例提示, 后续可 emit 'request-config-chat'
 *  让 ChatPage 把 ConfigAssistant 输入框获焦 + 预填 "为 XX 创建审批流程". */
function onRequestConfigChat() {
  // eslint-disable-next-line no-console
  console.log('[ProcessDesignerPanel] request-config-chat — appId=', props.appId)
  alert('用右下角配置助手对话创建首个审批流程, 比如:\n• "为借书申请加管理员审批流程"\n• "新建报销审批: 部门主管 → 财务复核 → 总经理审批"\n• "为申请单加一个三级审批流"')
}

/** O2: 算 mock 实例进度 — 简化策略:
 *  - 总节点数 n, 已完成 = floor((n - 1) / 2) (start + 第 1 个审批)
 *  - currentNodeId = 第 floor((n - 1) / 2) 个 (即 mid 节点)
 *  - pending = mid+1..end
 *  - history: 给每个 completed 节点编 by + at (从 startedAt 倒推 X 分钟)
 *  - currentApprover: 从 MOCK_APPROVERS 取 mid index
 */
function calcMockInstanceProgress(orderedIds: string[]): void {
  const n = orderedIds.length
  if (n === 0) {
    mockInstance.value.completedNodes = []
    mockInstance.value.pendingNodes = []
    mockInstance.value.currentNodeId = null
    mockInstance.value.history = []
    return
  }
  // 至少 1 个 completed (start), 中间 1 个 current; 其余 pending.
  const completedCount = Math.max(1, Math.floor((n - 1) / 2))
  const currentIdx = Math.min(completedCount, n - 1)
  const completedNodes = orderedIds.slice(0, completedCount)
  const currentNodeId = orderedIds[currentIdx] || null
  const pendingNodes = orderedIds.slice(currentIdx + 1)

  // history: 已完成的每个节点编 by + at (从 startedAt 起每隔 +15 min)
  const startMs = Date.parse(mockInstance.value.startedAt) || Date.now() - 3 * 60_000
  const history: MockHistoryEntry[] = []
  for (let i = 0; i < completedNodes.length; i++) {
    const id = completedNodes[i]
    const by = MOCK_APPROVERS[i % MOCK_APPROVERS.length]
    const action = MOCK_ACTIONS[i] || '审批通过'
    const ts = new Date(startMs + i * 15 * 60_000)
    const at = `${ts.getHours().toString().padStart(2, '0')}:${ts.getMinutes().toString().padStart(2, '0')}`
    history.push({ nodeId: id, action, by, at })
  }
  // currentApprover: 用 currentIdx 对应名
  const currentApprover = MOCK_APPROVERS[currentIdx % MOCK_APPROVERS.length] || '张三'

  mockInstance.value.completedNodes = completedNodes
  mockInstance.value.currentNodeId = currentNodeId
  mockInstance.value.pendingNodes = pendingNodes
  mockInstance.value.history = history
  mockInstance.value.currentApprover = currentApprover
}

/** O2: 把 mock instance 状态画到 x6 节点 attrs.
 *  completed: 绿色 stroke + 浅绿 fill + ✓ 前缀
 *  current: 蓝色 stroke + brand-soft fill + 脉冲 class
 *  pending: 默认 (灰边 / 浅 fill)
 */
function paintInstanceProgress(): void {
  const g = graphRef.value
  if (!g) return
  const orderedIds = orderedNodeIds()
  calcMockInstanceProgress(orderedIds)
  const m = mockInstance.value
  for (const id of orderedIds) {
    const node = g.getCellById(id) as X6Node | null
    if (!node) continue
    const st = nodeStates[id]
    const def = st ? getNodeDef(st.type) : null
    const baseLabel = st?.label || (def?.label || '')
    const icon = def?.icon || ''
    let status: NodeProgressStatus = 'pending'
    if (m.completedNodes.includes(id)) status = 'completed'
    else if (m.currentNodeId === id) status = 'current'

    if (status === 'completed') {
      node.attr('body/stroke', '#16a34a')
      node.attr('body/strokeWidth', 2.5)
      node.attr('body/fill', '#dcfce7')
      node.attr('label/text', `✓  ${icon}  ${baseLabel}`)
      node.attr('label/fill', '#14532d')
      node.removeAttrByPath('body/strokeDasharray')
      // 静态 stroke (no animation)
    } else if (status === 'current') {
      node.attr('body/stroke', '#2563eb')
      node.attr('body/strokeWidth', 3)
      node.attr('body/fill', '#dbeafe')
      node.attr('label/text', `${icon}  ${baseLabel}`)
      node.attr('label/fill', '#1e40af')
      // 加 CSS class 让 SVG 节点 animate (脉冲)
      const view = g.findViewByCell(node)
      if (view) {
        const el = (view as unknown as { container?: SVGGElement }).container
        if (el && el.classList) {
          el.classList.add('pdp-node-current-pulse')
        }
      }
    } else {
      // pending — 灰
      node.attr('body/stroke', '#cbd5e1')
      node.attr('body/strokeWidth', 1.5)
      node.attr('body/fill', '#f8fafc')
      node.attr('label/text', `${icon}  ${baseLabel}`)
      node.attr('label/fill', '#64748b')
      const view = g.findViewByCell(node)
      if (view) {
        const el = (view as unknown as { container?: SVGGElement }).container
        if (el && el.classList) {
          el.classList.remove('pdp-node-current-pulse')
        }
      }
    }
  }
}

/** O2: 还原节点默认 stroke + fill — 给 setViewMode(false) 切到 edit 时清 mock 视觉. */
function clearInstanceProgress(): void {
  const g = graphRef.value
  if (!g) return
  for (const id of Object.keys(nodeStates)) {
    const node = g.getCellById(id) as X6Node | null
    if (!node) continue
    const st = nodeStates[id]
    if (!st) continue
    const def = getNodeDef(st.type)
    if (!def) continue
    const spec = buildNodeSpec(st.type, st.label || def.label, def.icon)
    const bodyAttrs = ((spec.attrs as Record<string, unknown>)?.body || {}) as Record<string, unknown>
    const labelAttrs = ((spec.attrs as Record<string, unknown>)?.label || {}) as Record<string, unknown>
    if (typeof bodyAttrs.fill === 'string') node.attr('body/fill', bodyAttrs.fill)
    if (typeof bodyAttrs.stroke === 'string') node.attr('body/stroke', bodyAttrs.stroke)
    if (typeof bodyAttrs.strokeWidth === 'number') node.attr('body/strokeWidth', bodyAttrs.strokeWidth)
    if (typeof labelAttrs.fill === 'string') node.attr('label/fill', labelAttrs.fill)
    node.attr('label/text', `${def.icon}  ${st.label || def.label}`)
    const view = g.findViewByCell(node)
    if (view) {
      const el = (view as unknown as { container?: SVGGElement }).container
      if (el && el.classList) el.classList.remove('pdp-node-current-pulse')
    }
  }
}

async function onSelectProcess(processId: string) {
  if (activeProcessId.value === processId) return
  // 切流程: 清当前 canvas state, 准备渲染新流程
  selectedNodeId.value = null
  for (const k of Object.keys(nodeStates)) delete nodeStates[k]
  const g = graphRef.value
  if (g) {
    g.clearCells()
    nodeCount.value = 0
    edgeCount.value = 0
  }
  activeProcessId.value = processId
  lastSavedAt.value = null
  // 默认进 read-only — 切到编辑才能改
  readOnly.value = true
  if (g) {
    g.setInteracting(() => ({
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
      if (props.formId && processList.value.length > 0) {
        const match = processList.value.find(p => p.form_id === props.formId)
        if (match) {
          activeProcessId.value = match.id
          autoSelected = match.id
        }
      }
      // 没匹配但只有 1 个流程 → 自动选中
      if (!activeProcessId.value && processList.value.length === 1) {
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

function clearSelection() {
  selectedNodeId.value = null
}

function onPropsChange() {
  // 把当前选中 node 的 label 同步回 x6.
  const g = graphRef.value
  const sel = selectedNode.value
  if (!g || !sel) return
  const node = g.getCellById(sel.id) as X6Node | null
  if (!node) return
  const def = getNodeDef(sel.type)
  const icon = def?.icon || ''
  ;(node as X6Node).attr('label/text', `${icon}  ${sel.label}`)
}

function onFitContent() {
  const g = graphRef.value
  if (!g) return
  if (g.getNodes().length === 0) return
  g.zoomToFit({ padding: 32, maxScale: 1.2 })
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
interface ProcessDefinitionOut {
  process_name: string
  nodes: ProcessDefinitionNodeOut[]
  edges: ProcessDefinitionEdgeOut[]
}

function serializeGraph(): ProcessDefinitionOut {
  const g = graphRef.value
  if (!g) {
    return { process_name: '', nodes: [], edges: [] }
  }
  const nodes: ProcessDefinitionNodeOut[] = []
  for (const node of g.getNodes()) {
    const id = node.id
    const st = nodeStates[id]
    const data = (node.getData() || {}) as { type?: string }
    const type = st?.type || data.type || 'unknown'
    const pos = node.getPosition()
    // props = nodeStates[id] 里除 id/type/label/x/y/key 之外的所有字段
    const propsObj: Record<string, unknown> = {}
    if (st) {
      for (const [k, v] of Object.entries(st)) {
        if (['id', 'type', 'label', 'x', 'y', 'key'].includes(k)) continue
        if (v === undefined) continue
        propsObj[k] = v as unknown
      }
    }
    nodes.push({
      id,
      type,
      label: st?.label || (typeof node.getAttrByPath('label/text') === 'string'
        ? String(node.getAttrByPath('label/text') ?? '')
        : ''),
      position: { x: pos.x, y: pos.y },
      props: propsObj,
    })
  }
  const edges: ProcessDefinitionEdgeOut[] = []
  for (const edge of g.getEdges()) {
    const sourceId = (edge as X6Edge).getSourceCellId() || ''
    const targetId = (edge as X6Edge).getTargetCellId() || ''
    if (!sourceId || !targetId) continue
    const labelData = edge.getLabels()
    const labelTxt = Array.isArray(labelData) && labelData.length > 0
      ? String((labelData[0] as { attrs?: { label?: { text?: string } } })?.attrs?.label?.text ?? '')
      : ''
    const edgeData = (edge.getData() || {}) as { condition?: string }
    edges.push({
      id: edge.id,
      source: sourceId,
      target: targetId,
      label: labelTxt || undefined,
      condition: edgeData.condition || undefined,
    })
  }
  return {
    process_name: activeProcess.value?.name || activeProcess.value?.code || '',
    nodes,
    edges,
  }
}

/** 2026-05-28: 干净的拓扑自动布局 —— apaas 原始 x/y 错位 (审批节点 x=348 / 开始结束 x=372)
 *  导致连线歪七扭八。业务视角是只读预览, 直接按"入边数=0 的为起点 + BFS 分层"重排:
 *  同层水平居中铺开, 逐层向下 → 线性流变成一条直的竖线, 分支左右对称。 */
function computeAutoLayout(
  nodes: { id: string }[],
  edges: { source: string; target: string }[],
): Map<string, { x: number; y: number }> {
  const TOP = 40, VGAP = 110, HGAP = 200, CENTER = 320
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

/** H2: 渲染本地 ProcessDefinition (从 GET /definition 拿到的 nodes/edges) 到 x6. */
function renderDefinition(defNodes: ProcessDefinitionNodeOut[], defEdges: ProcessDefinitionEdgeOut[]) {
  const g = graphRef.value
  if (!g) return
  g.clearCells()
  for (const k of Object.keys(nodeStates)) delete nodeStates[k]
  // 用拓扑自动布局覆盖 apaas 原始坐标 (拉直连线)
  const layout = computeAutoLayout(defNodes, defEdges)
  // 节点
  for (const n of defNodes) {
    const type = n.type as NodeType
    const def = getNodeDef(type)
    if (!def) {
      // 未知 type — 跳过, 不挡其他节点渲染
      continue
    }
    const spec = buildNodeSpec(type, n.label || def.label, def.icon)
    const p = layout.get(n.id) || n.position || { x: 100, y: 100 }
    g.addNode({
      id: n.id,
      x: p.x,
      y: p.y,
      ...spec,
      data: { type, color: getNodeColor(type) },
    } as never)
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
      g.addEdge({
        id: e.id,
        source: e.source,
        target: e.target,
        labels: e.label ? [{ attrs: { label: { text: e.label } } }] : undefined,
        data: e.condition ? { condition: e.condition } : undefined,
        attrs: {
          line: {
            stroke: '#94a3b8',
            strokeWidth: 1.5,
            targetMarker: { name: 'classic', size: 7 },
          },
        },
      } as never)
    } catch {
      // ignore bad edge
    }
  }
  refreshCounts(g)
  // O2: 渲染后, 如果当前是业务视角, 立即画 mock instance 进度
  if (readOnly.value) {
    paintInstanceProgress()
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
      renderDefinition(resp.nodes || [], resp.edges || [])
      ElMessage.info({
        message: `已从 apaas 平台加载流程 — 编辑后点"保存"会覆盖本地副本, 点"部署"才同步回 apaas`,
        duration: 4000,
      })
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

async function onSave() {
  if (!props.appId || !activeProcess.value) {
    ElMessage.warning('请先选择左侧流程')
    return
  }
  if (saving.value) return
  saving.value = true
  try {
    const payload = serializeGraph()
    const resp = await request.post<unknown, {
      ok: boolean
      process_id?: string
      version?: number
      updated_at?: string
      message?: string
      error_code?: string
    }>(`/applications/${props.appId}/processes/${activeProcess.value.id}/save-definition`, payload)
    if (resp?.ok) {
      lastSavedAt.value = resp.updated_at || new Date().toISOString()
      ElMessage.success(`已保存 (v${resp.version ?? 1})`)
    } else {
      ElMessage.error(resp?.message || resp?.error_code || '保存失败')
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    ElMessage.error(err?.response?.data?.detail || err?.message || '网络错误')
  } finally {
    saving.value = false
  }
}

/** I4: 把本地 definition 真同步到 apaas 平台 — 先保存再调 deploy. */
async function onDeploy() {
  if (!props.appId || !activeProcess.value) {
    ElMessage.warning('请先选择左侧流程')
    return
  }
  if (deploying.value || saving.value) return

  // Step 1: 先保存最新 definition (避免漂移)
  saving.value = true
  try {
    const payload = serializeGraph()
    const saveResp = await request.post<unknown, {
      ok: boolean
      version?: number
      updated_at?: string
      message?: string
      error_code?: string
    }>(`/applications/${props.appId}/processes/${activeProcess.value.id}/save-definition`, payload)
    if (!saveResp?.ok) {
      ElMessage.error(`保存失败: ${saveResp?.message || saveResp?.error_code || '未知错误'}`)
      return
    }
    lastSavedAt.value = saveResp.updated_at || new Date().toISOString()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    ElMessage.error(`保存失败: ${err?.response?.data?.detail || err?.message || '网络错误'}`)
    return
  } finally {
    saving.value = false
  }

  // Step 2: 调 deploy endpoint
  deploying.value = true
  try {
    const resp = await request.post<unknown, {
      ok: boolean
      deployed_version?: number
      deployed_at?: string
      apaas_app_id?: string
      menu_id?: string
      node_count?: number
      edge_count?: number
      unsupported_nodes?: Array<{ id: string; type: string; label?: string; reason?: string }>
      apaas_response_code?: string
      message?: string
      error_code?: string
    }>(`/applications/${props.appId}/processes/${activeProcess.value.id}/deploy`)

    if (resp?.ok) {
      lastDeployedAt.value = resp.deployed_at || new Date().toISOString()
      lastDeployedVersion.value = resp.deployed_version ?? null
      const unsupportedCount = (resp.unsupported_nodes || []).length
      if (unsupportedCount > 0) {
        const typesSet = new Set((resp.unsupported_nodes || []).map(n => n.type).filter(Boolean))
        ElMessage.warning({
          message: `已部署 v${resp.deployed_version ?? 1} (${resp.node_count ?? 0} 节点), 但 ${unsupportedCount} 类节点暂未支持: ${Array.from(typesSet).join(', ')} (P6 待实现)`,
          duration: 7000,
        })
      } else {
        ElMessage.success(`已部署到 apaas 平台 (v${resp.deployed_version ?? 1}, ${resp.node_count ?? 0} 节点)`)
      }
    } else {
      const code = resp?.error_code || 'DEPLOY_FAILED'
      if (code === 'APP_NOT_DEPLOYED') {
        ElMessage.error('应用尚未部署到 apaas 平台 — 先部署应用再部署流程')
      } else if (code === 'PROCESS_DEFINITION_NOT_FOUND') {
        ElMessage.error('本地无该流程定义 — 请先保存再部署')
      } else {
        ElMessage.error(resp?.message || code)
      }
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string; message?: string } }; message?: string }
    ElMessage.error(err?.response?.data?.detail || err?.response?.data?.message || err?.message || '部署网络错误')
  } finally {
    deploying.value = false
  }
}

function onAiQuery(query: string) {
  // P2 接 ConfigAssistant — 当前 alert 占位
  alert(`AI 提问占位 — P2 转给 ConfigAssistant:\n${query}`)
}

onMounted(async () => {
  await reloadProcessList()
  await nextTick()
  // 流程 list 加载完, 不管有没有选中先 init graph 让 canvas 出现
  // (canvas 区域始终显示, 是否有 node 由 activeProcess 决定)
  if (processList.value.length > 0) {
    initGraph()
  }
})

onBeforeUnmount(() => {
  graphRef.value?.dispose()
  graphRef.value = null
})

watch(
  () => props.appId,
  async (next, prev) => {
    if (next === prev) return
    // 应用切了: 清 graph + state, 重新拉 list
    graphRef.value?.dispose()
    graphRef.value = null
    selectedNodeId.value = null
    activeProcessId.value = null
    for (const k of Object.keys(nodeStates)) delete nodeStates[k]
    nodeCount.value = 0
    edgeCount.value = 0
    processList.value = []
    await reloadProcessList()
    await nextTick()
    if (processList.value.length > 0) {
      initGraph()
    }
  },
)

watch(
  () => props.formId,
  (next) => {
    // ChatPage 切菜单 → 尝试匹配对应流程自动选中
    if (next && processList.value.length > 0 && !activeProcessId.value) {
      const match = processList.value.find(p => p.form_id === next)
      if (match) {
        onSelectProcess(match.id)
      }
    }
  },
)

// 一旦 list 拉到 (从 0 → N), 触发 initGraph (template 才有 containerRef)
watch(
  () => processList.value.length,
  async (next, prev) => {
    if (next > 0 && prev === 0 && !graphRef.value) {
      await nextTick()
      if (containerRef.value && !graphRef.value) {
        initGraph()
      }
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

/* O2: 老 .pdp-mode-badge 移除 — segmented control 代替 (新 .pdp-mode-segment 定义在文件末尾 O2 块). */

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
/* 设计模式 center — apaas 原生编辑器 iframe 占满中央区 (sidebar 右侧 flex:1). */
.pdp-iframe {
  flex: 1;
  min-width: 0;
  min-height: 0;
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

/* ════════════════════════════════════════════════════════════
   O2: 业务视角 — banner / segmented control / timeline / 节点脉冲
   ════════════════════════════════════════════════════════════ */

/* ─── 顶部业务视角 banner ─── */
.pdp-biz-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 24px;
  background: var(--brand-soft, #eff6ff);
  color: var(--brand, #2563eb);
  border-bottom: 1px solid var(--brand, #2563eb);
  flex-shrink: 0;
  font-size: 13px;
  line-height: 1.45;
}
.pdp-biz-banner-icon {
  font-size: 16px;
  flex-shrink: 0;
}
.pdp-biz-banner-text {
  flex: 1;
  color: var(--text);
}
.pdp-biz-banner-text strong {
  color: var(--brand, #2563eb);
  font-weight: 600;
}
.pdp-biz-banner-cta {
  flex-shrink: 0;
  height: 30px;
  padding: 0 14px;
  border-radius: 15px;
  background: var(--brand, #2563eb);
  color: #fff;
  border: none;
  cursor: pointer;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 500;
  transition: background 0.12s, transform 0.12s;
}
.pdp-biz-banner-cta:hover {
  background: var(--brand-hover, #1d4ed8);
  transform: translateY(-1px);
}

/* ─── 顶部 segmented control ─── */
.pdp-mode-segment {
  display: inline-flex;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 2px;
  margin-right: 4px;
}
.pdp-mode-segment-btn {
  height: 26px;
  padding: 0 12px;
  background: transparent;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-3);
  transition: background 0.12s, color 0.12s;
}
.pdp-mode-segment-btn:hover:not(.is-active) {
  color: var(--text);
}
.pdp-mode-segment-btn.is-active {
  background: var(--surface);
  color: var(--brand);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
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

/* ─── 右: 历史轨迹时间轴 panel ─── */
.pdp-timeline {
  width: 280px;
  flex-shrink: 0;
  border-left: 1px solid var(--line);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.pdp-timeline-head {
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.pdp-timeline-title {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.pdp-timeline-sub {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-4);
}
.pdp-timeline-list {
  list-style: none;
  margin: 0;
  padding: 16px 18px 24px;
  flex: 1;
  overflow-y: auto;
  position: relative;
}
/* 左竖线 — 从第一个 dot 到最后一个 dot */
.pdp-timeline-list::before {
  content: '';
  position: absolute;
  left: 26px;
  top: 28px;
  bottom: 36px;
  width: 1px;
  background: var(--line);
}
.pdp-timeline-item {
  position: relative;
  padding: 0 0 18px 28px;
  min-height: 36px;
}
.pdp-timeline-item:last-child {
  padding-bottom: 0;
}
.pdp-timeline-dot {
  position: absolute;
  left: 0;
  top: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  background: var(--line-strong, #cbd5e1);
  z-index: 1;
}
.pdp-timeline-dot.is-completed {
  background: #16a34a;
}
.pdp-timeline-dot.is-current {
  background: var(--brand, #2563eb);
  box-shadow: 0 0 0 4px var(--brand-soft, #dbeafe);
  animation: pdp-pulse-dot 1.5s ease-in-out infinite;
}
.pdp-timeline-dot.is-pending {
  background: var(--surface);
  border: 1.5px solid var(--line-strong, #cbd5e1);
  color: var(--text-4);
}
.pdp-timeline-body {
  font-size: 12.5px;
  line-height: 1.5;
}
.pdp-timeline-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pdp-timeline-name {
  font-weight: 500;
  color: var(--text);
}
.pdp-timeline-item.is-pending .pdp-timeline-name {
  color: var(--text-3);
  font-weight: 400;
}
.pdp-timeline-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 10.5px;
  font-weight: 500;
  background: var(--brand-soft, #dbeafe);
  color: var(--brand, #2563eb);
}
.pdp-timeline-meta {
  margin: 3px 0 0;
  font-size: 11.5px;
  color: var(--text-4);
}
.pdp-timeline-meta strong {
  color: var(--brand, #2563eb);
}

/* ─── x6 节点脉冲动画 (current 节点 SVG container) ─── */
@keyframes pdp-node-current-pulse {
  0%   { filter: drop-shadow(0 0 0 rgba(37, 99, 235, 0.4)); }
  50%  { filter: drop-shadow(0 0 6px rgba(37, 99, 235, 0.7)); }
  100% { filter: drop-shadow(0 0 0 rgba(37, 99, 235, 0.4)); }
}
:deep(.pdp-node-current-pulse) {
  animation: pdp-node-current-pulse 1.6s ease-in-out infinite;
}

@keyframes pdp-pulse-dot {
  0%   { box-shadow: 0 0 0 4px var(--brand-soft, #dbeafe); }
  50%  { box-shadow: 0 0 0 7px rgba(37, 99, 235, 0.18); }
  100% { box-shadow: 0 0 0 4px var(--brand-soft, #dbeafe); }
}
</style>

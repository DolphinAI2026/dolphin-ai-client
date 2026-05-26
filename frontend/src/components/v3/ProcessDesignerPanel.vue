<!-- ProcessDesignerPanel.vue — Native 流程设计器面板 (替 apaas process designer iframe).

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

    <!-- 应用无流程 -->
    <div v-else-if="processList.length === 0" class="pdp-empty">
      <div class="pdp-empty-icon">🔀</div>
      <h3>应用暂无流程</h3>
      <p>用配置助手对话创建审批流程, 或在表单菜单上挂流程后这里会出现.</p>
    </div>

    <!-- 有流程: 显完整设计器 -->
    <template v-else>
      <!-- 中央顶部 toolbar -->
      <header class="pdp-head">
        <div class="pdp-head-meta">
          <h1 class="pdp-title">
            {{ activeProcess?.name || activeProcess?.code || '选择左侧流程' }}
            <span v-if="readOnly" class="pdp-mode-badge pdp-mode-view" title="只读模式 — 切到编辑才能改">查看</span>
            <span v-else class="pdp-mode-badge pdp-mode-edit" title="编辑模式 — 加节点 / 连线">编辑</span>
          </h1>
          <p class="pdp-sub">
            <span class="pdp-stat">{{ statsLine }}</span>
          </p>
        </div>
        <div class="pdp-head-actions">
          <button class="pdp-btn pdp-btn-ghost" @click="onFitContent" title="适应画布">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7V3h4M21 7V3h-4M3 17v4h4M21 17v4h-4"/></svg>
            适应
          </button>
          <button class="pdp-btn pdp-btn-ghost" @click="toggleEditMode" :title="readOnly ? '切到编辑模式' : '切到查看模式'">
            {{ readOnly ? '✏️ 编辑' : '👁 查看' }}
          </button>
          <button class="pdp-btn pdp-btn-ghost" :disabled="true" title="P2 接入">自动布局</button>
          <button class="pdp-btn pdp-btn-ghost" :disabled="true" title="P2 接入">试跑</button>
          <button class="pdp-btn pdp-btn-primary" :disabled="!activeProcess" @click="onSave">保存</button>
        </div>
      </header>

      <div class="pdp-body">
        <!-- 左 sidebar: 流程列表 + 节点库 -->
        <aside class="pdp-sidebar" aria-label="流程列表 + 节点库">
          <!-- ── 流程列表 panel ────────────────────────────────── -->
          <div class="pdp-section">
            <button
              class="pdp-section-head"
              @click="processListCollapsed = !processListCollapsed"
              :aria-expanded="!processListCollapsed"
            >
              <span class="pdp-cat-arrow" :class="{ 'is-open': !processListCollapsed }">▸</span>
              <span class="pdp-cat-label">流程列表</span>
              <span class="pdp-cat-count">{{ processList.length }}</span>
            </button>
            <div v-if="!processListCollapsed" class="pdp-process-list">
              <button
                v-for="p in processList"
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

          <!-- ── 节点库 ────────────────────────────────────────── -->
          <h4 class="pdp-sidebar-title">节点库</h4>
          <div class="pdp-cat-list">
            <div
              v-for="cat in NODE_CATEGORIES"
              :key="cat.code"
              class="pdp-cat"
              :data-cat="cat.code"
            >
              <button
                class="pdp-cat-head"
                @click="toggleCategory(cat.code)"
                :aria-expanded="!collapsed[cat.code]"
              >
                <span class="pdp-cat-arrow" :class="{ 'is-open': !collapsed[cat.code] }">▸</span>
                <span class="pdp-cat-label">{{ cat.label }}</span>
                <span class="pdp-cat-count">{{ cat.nodes.length }}</span>
              </button>
              <div v-if="!collapsed[cat.code]" class="pdp-chip-grid">
                <button
                  v-for="n in cat.nodes"
                  :key="n.type"
                  class="pdp-chip"
                  :data-cat="cat.code"
                  :disabled="readOnly || !activeProcess"
                  :title="readOnly ? '切到编辑模式才能加节点' : `加 ${n.label}`"
                  @click="onSidebarNodeClick(n.type)"
                >
                  <span class="pdp-chip-icon">{{ n.icon }}</span>
                  <span class="pdp-chip-label">{{ n.label }}</span>
                </button>
              </div>
            </div>
          </div>
          <p class="pdp-sidebar-foot">
            {{ readOnly ? '只读模式 — 切到编辑模式后才能加节点' : '点击节点添加到画布 — 拖拽连线在画布上拖' }}
          </p>
        </aside>

        <!-- 中央 x6 canvas -->
        <div class="pdp-canvas-wrap">
          <div ref="containerRef" class="pdp-canvas"></div>
          <div v-if="!nodeCount && activeProcess" class="pdp-canvas-hint">
            <div class="pdp-canvas-hint-icon">⊕</div>
            <p v-if="readOnly">
              <strong>"{{ activeProcess.name || activeProcess.code }}"</strong> 流程详情拉取 P3 接入
              <br />当前空画布 — 切到编辑模式可临时拖入节点试设计
            </p>
            <p v-else>左侧选节点, 点击添加到这里</p>
          </div>
          <div v-if="!activeProcess" class="pdp-canvas-hint">
            <div class="pdp-canvas-hint-icon">👈</div>
            <p>从左侧"流程列表"选择一个流程</p>
          </div>
        </div>

        <!-- 右节点属性面板 -->
        <ProcessNodePropsPanel
          v-if="selectedNode"
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
import { Graph, type Node as X6Node } from '@antv/x6'
import ProcessNodePropsPanel from './ProcessNodePropsPanel.vue'
import request from '@/utils/request'
import {
  NODE_CATEGORIES,
  type NodeType,
  type NodeCategoryCode,
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

const collapsed = reactive<Record<NodeCategoryCode, boolean>>({
  entry: false,
  approval: false,
  logic: false,
  action: false,
})

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

const activeProcess = computed<ProcessItem | null>(() => {
  if (!activeProcessId.value) return null
  return processList.value.find(p => p.id === activeProcessId.value) || null
})

const selectedNode = computed<ProcessNode | null>(() => {
  if (!selectedNodeId.value) return null
  return nodeStates[selectedNodeId.value] || null
})

const statsLine = computed(() => {
  const entryN = Object.values(nodeStates).filter(n => getNodeCategoryCode(n.type) === 'entry').length
  const procCount = processList.value.length
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

function toggleCategory(code: NodeCategoryCode) {
  collapsed[code] = !collapsed[code]
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

function getCanvasCenter(): { x: number; y: number } {
  const g = graphRef.value
  if (!g || !containerRef.value) return { x: 200, y: 200 }
  const box = containerRef.value.getBoundingClientRect()
  // 简化: 用容器中心 + 累计 offset 防节点重叠
  const offsetCount = nodeCount.value
  const offsetX = (offsetCount % 4) * 40
  const offsetY = Math.floor(offsetCount / 4) * 40
  return {
    x: Math.max(80, box.width / 2 - 80 + offsetX),
    y: Math.max(80, box.height / 2 - 40 + offsetY),
  }
}

function onSidebarNodeClick(type: NodeType) {
  if (readOnly.value) {
    alert('当前是查看模式 — 点顶部 "编辑" 切到编辑模式后才能加节点')
    return
  }
  if (!activeProcess.value) {
    alert('请先从左侧 "流程列表" 选择一个流程')
    return
  }
  const g = graphRef.value
  if (!g) return
  const def = getNodeDef(type)
  if (!def) return
  const id = `${type}_${Math.random().toString(36).slice(2, 8)}`
  const spec = buildNodeSpec(type, def.label, def.icon)
  const pos = getCanvasCenter()
  g.addNode({
    id,
    x: pos.x,
    y: pos.y,
    ...spec,
    data: { type, color: getNodeColor(type) },
  } as never)
  nodeStates[id] = makeDefaultNode(id, type, def.label)
  nodeStates[id].x = pos.x
  nodeStates[id].y = pos.y
  selectedNodeId.value = id
}

function toggleEditMode() {
  if (!activeProcess.value) {
    alert('请先从左侧 "流程列表" 选择一个流程')
    return
  }
  readOnly.value = !readOnly.value
  // 同步 x6 interacting 配置 — read-only 时禁止 node 移动 + 连线
  const g = graphRef.value
  if (g) {
    g.setInteracting(() => (readOnly.value
      ? { nodeMovable: false, edgeMovable: false, edgeLabelMovable: false, magnetConnectable: false, arrowheadMovable: false }
      : { nodeMovable: true }
    ))
  }
}

function onSelectProcess(processId: string) {
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
  // 默认进 read-only — detail 拉取留 P3, 当前空画布 + 提示
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
  // P3: 这里应调 GET /applications/{appId}/processes/{processId}/detail 拉 BPMN
  // → 解析 nodes/edges → graph.addNode/addEdge. 当前 backend 没 query API 故跳.
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
      if (props.formId && processList.value.length > 0) {
        const match = processList.value.find(p => p.form_id === props.formId)
        if (match) {
          activeProcessId.value = match.id
        }
      }
      // 没匹配但只有 1 个流程 → 自动选中
      if (!activeProcessId.value && processList.value.length === 1) {
        activeProcessId.value = processList.value[0].id
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

function onSave() {
  // P2 接 set_apaas_app_process — 当前 alert 提示走配置助手
  alert('保存流程 — P2 接入, 当前请用配置助手对话:\n"把当前流程保存到平台"')
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

/* ───── 编辑/查看 mode badge ───── */
.pdp-mode-badge {
  display: inline-flex;
  align-items: center;
  margin-left: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.3px;
  vertical-align: 2px;
}
.pdp-mode-view {
  background: var(--surface-2);
  color: var(--text-3);
  border: 1px solid var(--line);
}
.pdp-mode-edit {
  background: var(--warn-soft, #fef3c7);
  color: var(--warn, #92400e);
  border: 1px solid var(--warn, #f59e0b);
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
</style>

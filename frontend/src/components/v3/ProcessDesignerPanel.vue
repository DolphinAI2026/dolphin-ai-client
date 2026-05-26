<!-- ProcessDesignerPanel.vue — Native 流程设计器面板 (替 apaas process designer iframe).

  2026-05-26 design-v3 P1-N3: 设计 tab + 流程 sub-tab 选中某菜单后,
  显该菜单对应 process 的 BPMN-like 节点图. 用 @antv/x6 渲染.

  P0 骨架:
    - 左 sidebar (200px): 节点类型 list, 点击拖到画布 (P0 仅点击添加, 拖拽真接 P1)
    - 中央 canvas: x6 Graph 实例
    - 右侧 props panel (240px, v-if=有选中): 节点属性编辑

  数据源:
    - P0 mock 4 节点 + 3 边 demo
    - P1 接 list_apaas_app_processes / list_apaas_app_menus 拿真 BPMN

  样式与 FormDesignerPanel 对齐 — var(--brand) / var(--surface) / var(--text) / var(--line)
-->
<template>
  <section class="pdp" aria-label="流程设计">
    <div v-if="!menuId" class="pdp-empty">
      <div class="pdp-empty-icon">🔀</div>
      <h3>选择一个流程</h3>
      <p>从左侧菜单点击带流程的表单, 这里显该表单的审批流程图.</p>
    </div>

    <template v-else>
      <header class="pdp-head">
        <div class="pdp-head-meta">
          <h1 class="pdp-title">{{ menuName || '流程设计' }}</h1>
          <p class="pdp-sub">
            <span class="pdp-stat">{{ nodeCount }} 节点 · {{ edgeCount }} 流转</span>
            <span class="pdp-chip pdp-chip-warn">P0 demo 节点 — 接真数据 P1</span>
          </p>
        </div>
        <div class="pdp-head-actions">
          <button class="pdp-btn pdp-btn-ghost" @click="onFitContent">适应画布</button>
          <button class="pdp-btn pdp-btn-ghost" :disabled="true" title="P1 接入">保存</button>
          <button class="pdp-btn pdp-btn-primary" :disabled="true" title="P1 接入">发布</button>
        </div>
      </header>

      <div class="pdp-body">
        <aside class="pdp-sidebar" aria-label="节点类型">
          <h4 class="pdp-sidebar-title">节点类型</h4>
          <ul class="pdp-node-list">
            <li
              v-for="t in NODE_TYPES"
              :key="t.id"
              class="pdp-node-item"
              :title="t.hint"
              @click="onSidebarItemClick(t)"
            >
              <span class="pdp-node-icon" :style="{ background: t.color }" />
              <div class="pdp-node-meta">
                <span class="pdp-node-label">{{ t.label }}</span>
                <span class="pdp-node-hint">{{ t.hint }}</span>
              </div>
            </li>
          </ul>
          <p class="pdp-sidebar-foot">点击节点添加 — 拖拽 P1 接入</p>
        </aside>

        <div class="pdp-canvas-wrap">
          <div ref="containerRef" class="pdp-canvas"></div>
        </div>

        <aside v-if="selected" class="pdp-props" aria-label="节点属性">
          <header class="pdp-props-head">
            <h4>节点属性</h4>
            <button class="pdp-icon-btn" title="清除选中" @click="clearSelection">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6 6 18M6 6l12 12"/>
              </svg>
            </button>
          </header>
          <div class="pdp-props-body">
            <label class="pdp-field">
              <span class="pdp-field-label">节点 ID</span>
              <input class="pdp-input pdp-input-readonly" :value="selected.id" readonly />
            </label>
            <label class="pdp-field">
              <span class="pdp-field-label">节点名称</span>
              <input class="pdp-input" v-model="selected.label" @input="onPropChange" />
            </label>
            <label class="pdp-field">
              <span class="pdp-field-label">类型</span>
              <input class="pdp-input pdp-input-readonly" :value="formatNodeType(selected.type)" readonly />
            </label>
            <label class="pdp-field">
              <span class="pdp-field-label">分配人 / 角色</span>
              <input
                class="pdp-input"
                v-model="selected.assignee"
                placeholder="留空表示由发起人指定"
                :disabled="selected.type === 'start' || selected.type === 'end'"
                @input="onPropChange"
              />
            </label>
            <p class="pdp-props-foot">编辑暂只改本地, 保存 / 发布 P1 接入.</p>
          </div>
        </aside>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, shallowRef, nextTick } from 'vue'
import { Graph } from '@antv/x6'

type NodeType = 'start' | 'user_task' | 'gateway' | 'end'

interface NodeTypeDef {
  id: NodeType
  label: string
  hint: string
  shape: 'circle' | 'rect' | 'polygon'
  color: string
}

interface SelectedNode {
  id: string
  label: string
  type: NodeType
  assignee: string
}

const props = defineProps<{
  appId: number
  menuId?: string
  menuName?: string
  formId?: string
}>()

const NODE_TYPES: NodeTypeDef[] = [
  { id: 'start',     label: '开始节点',  hint: '流程起点',            shape: 'circle',  color: '#10b981' },
  { id: 'user_task', label: '用户任务',  hint: '指派给人 / 角色审批', shape: 'rect',    color: '#3b82f6' },
  { id: 'gateway',   label: '网关',      hint: '条件分支 / 汇聚',     shape: 'polygon', color: '#f59e0b' },
  { id: 'end',       label: '结束节点',  hint: '流程终点',            shape: 'circle',  color: '#dc2626' },
]

const containerRef = ref<HTMLElement | null>(null)
const graphRef = shallowRef<Graph | null>(null)
const selected = ref<SelectedNode | null>(null)
const nodeCount = ref(0)
const edgeCount = ref(0)

/** Build node spec based on type. Reused for mock + sidebar-add. */
function buildNodeSpec(type: NodeType, label: string) {
  const def = (NODE_TYPES.find(t => t.id === type) || NODE_TYPES[1])!
  if (type === 'start' || type === 'end') {
    return {
      shape: 'circle',
      width: 56,
      height: 56,
      label,
      attrs: {
        body: { fill: def.color, stroke: def.color, strokeWidth: 2 },
        label: { fill: '#fff', fontSize: 12, fontWeight: 600 },
      },
    }
  }
  if (type === 'gateway') {
    return {
      shape: 'polygon',
      width: 70,
      height: 70,
      label,
      attrs: {
        body: {
          refPoints: '0,10 10,0 20,10 10,20',
          fill: '#fff7ed',
          stroke: def.color,
          strokeWidth: 2,
        },
        label: { fill: '#92400e', fontSize: 12, fontWeight: 500 },
      },
    }
  }
  // user_task default
  return {
    shape: 'rect',
    width: 120,
    height: 56,
    label,
    attrs: {
      body: {
        fill: '#fff',
        stroke: '#5B5BD6',
        strokeWidth: 1.5,
        rx: 6,
        ry: 6,
      },
      label: { fill: '#1f2937', fontSize: 13, fontWeight: 500 },
    },
  }
}

function formatNodeType(t: NodeType): string {
  const def = NODE_TYPES.find(x => x.id === t)
  return def?.label || t
}

/** Add mock 4 nodes + 3 edges. Caller is responsible for graph state. */
function loadMockGraph(graph: Graph) {
  const mockNodes = [
    { id: 'start',    type: 'start' as NodeType,     label: '开始',         x: 80,  y: 130 },
    { id: 'approve1', type: 'user_task' as NodeType, label: '部门审批',     x: 220, y: 120 },
    { id: 'approve2', type: 'user_task' as NodeType, label: '总经理审批',   x: 420, y: 120 },
    { id: 'end',      type: 'end' as NodeType,       label: '结束',         x: 620, y: 130 },
  ]
  mockNodes.forEach(n => {
    const spec = buildNodeSpec(n.type, n.label)
    graph.addNode({
      id: n.id,
      x: n.x,
      y: n.y,
      ...spec,
      data: { type: n.type, assignee: '' },
    } as any)
  })
  const mockEdges: Array<[string, string]> = [
    ['start', 'approve1'],
    ['approve1', 'approve2'],
    ['approve2', 'end'],
  ]
  mockEdges.forEach(([s, t]) => {
    graph.addEdge({
      source: s,
      target: t,
      attrs: {
        line: {
          stroke: '#94a3b8',
          strokeWidth: 1.5,
          targetMarker: { name: 'classic', size: 7 },
        },
      },
    })
  })
  refreshCounts(graph)
}

function refreshCounts(graph: Graph) {
  nodeCount.value = graph.getNodes().length
  edgeCount.value = graph.getEdges().length
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
  })

  // Sync selection with right panel.
  graph.on('node:click', ({ node }) => {
    const data = (node.getData() as { type?: NodeType; assignee?: string }) || {}
    const labelText = String((node.attr('label/text') as unknown) ?? '')
    selected.value = {
      id: node.id,
      label: labelText,
      type: data.type || 'user_task',
      assignee: data.assignee || '',
    }
  })
  graph.on('blank:click', () => {
    selected.value = null
  })

  graphRef.value = graph
  loadMockGraph(graph)
}

function onPropChange() {
  const g = graphRef.value
  const sel = selected.value
  if (!g || !sel) return
  const node = g.getCellById(sel.id)
  if (!node) return
  ;(node as any).attr('label/text', sel.label)
  const prev = (node.getData() as Record<string, any>) || {}
  node.setData({ ...prev, assignee: sel.assignee })
}

function clearSelection() {
  selected.value = null
}

function onFitContent() {
  const g = graphRef.value
  if (!g) return
  g.zoomToFit({ padding: 32, maxScale: 1.2 })
}

function onSidebarItemClick(t: NodeTypeDef) {
  // P0 — append a new node at a free spot near bottom-left of viewport.
  const g = graphRef.value
  if (!g) return
  const id = `${t.id}_${Date.now().toString(36)}`
  const spec = buildNodeSpec(t.id, t.label)
  g.addNode({
    id,
    x: 120 + (nodeCount.value % 5) * 40,
    y: 260 + Math.floor(nodeCount.value / 5) * 80,
    ...spec,
    data: { type: t.id, assignee: '' },
  } as any)
  refreshCounts(g)
}

onMounted(async () => {
  await nextTick()
  if (props.menuId) initGraph()
})

onBeforeUnmount(() => {
  graphRef.value?.dispose()
  graphRef.value = null
})

watch(
  () => props.menuId,
  async (next, prev) => {
    if (next === prev) return
    graphRef.value?.dispose()
    graphRef.value = null
    selected.value = null
    if (next) {
      await nextTick()
      initGraph()
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

.pdp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 24px 32px 18px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.pdp-title {
  margin: 0 0 6px;
  font-size: 22px;
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
.pdp-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
}
.pdp-chip-warn {
  background: #fef3c7;
  color: #92400e;
}

.pdp-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.pdp-btn {
  height: 32px;
  padding: 0 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid transparent;
  white-space: nowrap;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.pdp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.pdp-btn-ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--text);
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

.pdp-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.pdp-sidebar {
  width: 200px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--line);
  padding: 16px 12px;
  overflow-y: auto;
}
.pdp-sidebar-title {
  margin: 0 4px 10px;
  font-size: 11.5px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  color: var(--text-4);
}
.pdp-node-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pdp-node-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s;
}
.pdp-node-item:hover {
  background: var(--surface-2);
}
.pdp-node-icon {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  flex-shrink: 0;
}
.pdp-node-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.pdp-node-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
}
.pdp-node-hint {
  font-size: 11.5px;
  color: var(--text-4);
  margin-top: 2px;
}
.pdp-sidebar-foot {
  margin: 16px 4px 0;
  font-size: 11.5px;
  color: var(--text-4);
  line-height: 1.5;
}

.pdp-canvas-wrap {
  flex: 1;
  min-width: 0;
  background: #f8fafc;
  position: relative;
}
.pdp-canvas {
  width: 100%;
  height: 100%;
  position: absolute;
  inset: 0;
}

.pdp-props {
  width: 240px;
  flex-shrink: 0;
  background: var(--surface);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
}
.pdp-props-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
.pdp-props-head h4 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
}
.pdp-props-body {
  flex: 1;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
}
.pdp-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pdp-field-label {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.pdp-input {
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s;
}
.pdp-input:focus { border-color: var(--brand); }
.pdp-input:disabled { opacity: 0.5; cursor: not-allowed; }
.pdp-input-readonly {
  background: var(--surface-2);
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 12px;
}
.pdp-props-foot {
  margin: 4px 0 0;
  font-size: 11.5px;
  color: var(--text-4);
  line-height: 1.5;
}

.pdp-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.pdp-icon-btn:hover:not(:disabled) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
</style>

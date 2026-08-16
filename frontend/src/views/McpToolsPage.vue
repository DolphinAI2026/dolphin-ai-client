<!-- @deprecated Desktop remote MCP management is owned by Control Plane.
     This route remains for Web mode and legacy bookmarks. -->
<template>
  <BuilderFrame :breadcrumbs="[{ label: '设置' }, { label: 'MCP 工具' }]">
    <template #actions>
      <div class="mcp-server-chip" :title="serverInfo.endpoint">
        <span class="mcp-dot" :class="{ online: !loading && !error }"></span>
        <span class="mcp-server-name">{{ serverInfo.name || 'MCP server' }}</span>
        <code class="mcp-endpoint">{{ serverInfo.endpoint }}</code>
      </div>
    </template>

    <main class="mcp-main builder-page">
      <!-- 顶部摘要 -->
      <section class="mcp-summary">
        <div class="mcp-stat">
          <strong>{{ total }}</strong>
          <span>个工具</span>
        </div>
        <div class="mcp-stat">
          <strong>{{ categories.length }}</strong>
          <span>个分类</span>
        </div>
        <div class="mcp-stat">
          <strong>{{ serverInfo.transport }}</strong>
          <span>{{ serverInfo.auth_method }}</span>
        </div>
        <div class="mcp-summary-right">
          <input
            v-model="search"
            class="mcp-search"
            placeholder="搜索工具名 / 描述 / 参数…"
          />
        </div>
      </section>

      <div v-if="loading" class="mcp-state">
        <SkeletonCard :lines="4" with-avatar with-footer />
      </div>
      <div v-else-if="error" class="mcp-state error">
        <ErrorCard
          level="err"
          title="拉取 MCP 工具列表失败"
          :message="error"
          :actions="[{ label: '重试', primary: true, onClick: () => loadTools() }]"
        />
      </div>

      <template v-else>
        <!-- 分类筛选 -->
        <section class="mcp-tabs">
          <button
            class="mcp-tab"
            :class="{ active: activeCategory === 'all' }"
            @click="activeCategory = 'all'"
          >
            全部 <span class="mcp-tab-count">{{ total }}</span>
          </button>
          <button
            v-for="cat in categories"
            :key="cat.key"
            class="mcp-tab"
            :class="{ active: activeCategory === cat.key }"
            @click="activeCategory = cat.key"
          >
            {{ cat.label }} <span class="mcp-tab-count">{{ cat.tools.length }}</span>
          </button>
        </section>

        <section v-if="filteredTools.length === 0" class="mcp-empty">
          <EmptyState
            :variant="search ? 'filtered' : 'first'"
            :title="search ? '没有匹配的工具' : '当前分类下没有工具'"
            :desc="search ? `没找到 “${search}”。换个关键词试试，或者清空搜索看全部。` : '切换上方分类，或清空筛选条件查看所有工具。'"
          >
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            </template>
            <template v-if="search" #cta>
              <el-button @click="search = ''">清空搜索</el-button>
            </template>
          </EmptyState>
        </section>

        <!-- 工具卡片网格 -->
        <section v-else class="mcp-grid">
          <article
            v-for="tool in filteredTools"
            :key="tool.name"
            class="mcp-card"
            :class="{ expanded: expanded[tool.name] }"
          >
            <header class="mcp-card-header">
              <div class="mcp-card-title-line">
                <span class="mcp-card-icon" :class="`cat-${tool.category_key}`">
                  <AppIcon :name="categoryIcon(tool.category_key)" :size="16" />
                </span>
                <code class="mcp-card-name">{{ tool.name }}</code>
                <span class="mcp-card-cat">{{ tool.category_label }}</span>
              </div>
              <p class="mcp-card-title">{{ tool.title }}</p>
            </header>

            <div class="mcp-card-params">
              <div class="mcp-params-line">
                <span class="mcp-params-label">入参：</span>
                <span v-if="tool.params.length === 0" class="mcp-params-empty">无</span>
                <code
                  v-for="p in tool.params"
                  :key="p.name"
                  class="mcp-param-chip"
                  :class="{ required: p.required }"
                  :title="p.description || ''"
                >
                  {{ p.name }}<span class="mcp-param-type">: {{ p.type }}</span>
                </code>
              </div>
            </div>

            <div class="mcp-card-actions">
              <button
                v-if="tool.description"
                class="mcp-expand-btn"
                @click="expanded[tool.name] = !expanded[tool.name]"
              >
                {{ expanded[tool.name] ? '收起描述 ▲' : '展开详情 ▼' }}
              </button>
              <button class="mcp-try-btn" @click="openTryDialog(tool)" title="在线试调这个工具">
                <AppIcon name="zap" :size="12" /> 试调
              </button>
            </div>

            <pre v-if="expanded[tool.name] && tool.description" class="mcp-desc">{{ tool.description }}</pre>

            <details v-if="expanded[tool.name]" class="mcp-schema">
              <summary>JSON Schema</summary>
              <pre>{{ JSON.stringify(tool.input_schema, null, 2) }}</pre>
            </details>
          </article>
        </section>
      </template>

      <!-- 在线试调对话框 -->
      <div v-if="tryDialog.open" class="mcp-try-modal" @click.self="closeTryDialog">
        <div class="mcp-try-card">
          <header class="mcp-try-header">
            <div>
              <h3><AppIcon name="zap" :size="15" /> 试调 <code>{{ tryDialog.tool?.name }}</code></h3>
              <p>{{ tryDialog.tool?.title }}</p>
            </div>
            <button class="mcp-try-close" @click="closeTryDialog"><AppIcon name="x" :size="16" /></button>
          </header>

          <section class="mcp-try-body">
            <label class="mcp-try-label">
              入参 JSON（必填字段：
              <span v-for="p in tryDialog.tool?.params.filter(x => x.required) || []" :key="p.name" class="mcp-required-chip">
                {{ p.name }}: {{ p.type }}
              </span>
              <span v-if="!tryDialog.tool?.params.some(p => p.required)" class="mcp-required-empty">无必填</span>
              ）
            </label>
            <textarea
              v-model="tryDialog.argsText"
              class="mcp-try-input"
              :placeholder="tryDialog.placeholder"
              spellcheck="false"
            ></textarea>

            <div class="mcp-try-actions">
              <button class="mcp-try-run" :disabled="tryDialog.running" @click="runTry">
                {{ tryDialog.running ? '执行中...' : '▶ 执行' }}
              </button>
              <button class="mcp-try-cancel" @click="closeTryDialog">取消</button>
            </div>

            <div v-if="tryDialog.result" class="mcp-try-result">
              <header :class="['mcp-try-result-header', tryDialog.result.ok ? 'ok' : 'err']">
                {{ tryDialog.result.ok ? '✓ 成功' : '✗ 失败' }}
                <span class="mcp-try-cost">{{ tryDialog.result.elapsed_ms }}ms</span>
              </header>
              <pre class="mcp-try-result-body">{{ tryDialog.resultText }}</pre>
            </div>
          </section>
        </div>
      </div>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorCard from '@/components/states/ErrorCard.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import request from '@/utils/request'

interface ToolParam {
  name: string
  type: string
  description: string
  required: boolean
  default: any
}

interface McpTool {
  name: string
  title: string
  description: string
  category_key: string
  category_label: string
  input_schema: Record<string, any>
  params: ToolParam[]
  params_count: number
  required_count: number
}

interface CategoryGroup {
  key: string
  label: string
  tools: McpTool[]
}

const loading = ref(true)
const error = ref<string>('')
const total = ref(0)
const tools = ref<McpTool[]>([])
const categories = ref<CategoryGroup[]>([])
const serverInfo = ref<{ name: string; transport: string; endpoint: string; auth_method: string }>({
  name: '', transport: '', endpoint: '', auth_method: '',
})
const activeCategory = ref<string>('all')
const search = ref('')
const expanded = ref<Record<string, boolean>>({})

// 在线试调 dialog 状态
interface TryDialogState {
  open: boolean
  tool: McpTool | null
  argsText: string
  placeholder: string
  running: boolean
  result: { ok: boolean; elapsed_ms: number } | null
  resultText: string
}
const tryDialog = ref<TryDialogState>({
  open: false,
  tool: null,
  argsText: '{}',
  placeholder: '{}',
  running: false,
  result: null,
  resultText: '',
})

function openTryDialog(tool: McpTool) {
  // 给 args 准备一份初始模板（必填字段填示例值）
  const tpl: Record<string, any> = {}
  for (const p of tool.params) {
    if (!p.required) continue
    if (p.type === 'integer' || p.type === 'number') tpl[p.name] = 0
    else if (p.type === 'boolean') tpl[p.name] = false
    else if (p.type === 'array') tpl[p.name] = []
    else if (p.type === 'object') tpl[p.name] = {}
    else tpl[p.name] = ''
  }
  tryDialog.value = {
    open: true,
    tool,
    argsText: JSON.stringify(tpl, null, 2),
    placeholder: JSON.stringify(tpl, null, 2),
    running: false,
    result: null,
    resultText: '',
  }
}

function closeTryDialog() {
  tryDialog.value.open = false
}

async function runTry() {
  const tool = tryDialog.value.tool
  if (!tool) return
  tryDialog.value.running = true
  tryDialog.value.result = null
  tryDialog.value.resultText = ''
  let args: any
  try {
    args = JSON.parse(tryDialog.value.argsText || '{}')
  } catch (e: any) {
    tryDialog.value.running = false
    tryDialog.value.result = { ok: false, elapsed_ms: 0 }
    tryDialog.value.resultText = `JSON 解析失败: ${e?.message || e}`
    return
  }
  const t0 = Date.now()
  try {
    const data = await request.post<any, any>('/builder/invoke-mcp', {
      tool_name: tool.name,
      args,
    })
    const elapsed = Date.now() - t0
    tryDialog.value.result = { ok: !!data?.ok, elapsed_ms: elapsed }
    tryDialog.value.resultText = JSON.stringify(data, null, 2)
  } catch (e: any) {
    const elapsed = Date.now() - t0
    tryDialog.value.result = { ok: false, elapsed_ms: elapsed }
    tryDialog.value.resultText = `请求失败: ${e?.response?.data?.detail || e?.message || e}`
  } finally {
    tryDialog.value.running = false
  }
}

const filteredTools = computed(() => {
  let list = tools.value
  if (activeCategory.value !== 'all') {
    list = list.filter(t => t.category_key === activeCategory.value)
  }
  const q = search.value.trim().toLowerCase()
  if (q) {
    list = list.filter(t =>
      t.name.toLowerCase().includes(q) ||
      t.title.toLowerCase().includes(q) ||
      t.description.toLowerCase().includes(q) ||
      t.params.some(p => p.name.toLowerCase().includes(q))
    )
  }
  return list
})

function categoryIcon(key: string): string {
  return {
    apaas_introspect: 'search',
    doc: 'clipboard',
    app_lifecycle: 'rocket',
    env: 'globe',
    other: 'wrench',
  }[key] || 'wrench'
}

async function loadTools() {
  loading.value = true
  error.value = ''
  try {
    const data = await request.get<any, any>('/admin/mcp/tools')
    total.value = data.total
    tools.value = data.tools
    categories.value = data.categories
    serverInfo.value = data.server_info
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => { loadTools() })
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — MCP Hub visual refresh, template/script untouched.
   Refresh focus:
     - drop indigo-violet gradients (linear-gradient(#6366f1, #8b5cf6)) → flat var(--brand)
     - hardcoded greys (#e1e4ec / #6b7280 / #4b5563 / #f3f4f6) → var(--line) / --text-* / --surface-*
     - KPI strong: 22px → 24px tnum on Inter
     - card radius 10 → var(--r-4) 12; chip pills 4–6 → var(--r-2) 6
     - status header tokens → ok-soft / err-soft for solid semantics
     - row hover → var(--surface-2); icon soft → var(--brand-soft) by default
     - mono font normalised to var(--font-mono) with tnum
     - kept all class names; preserved dark theme block (rewritten via tokens so it
       inherits dark-mode automatically via v3-tokens.css cascade).
*/

/* Server chip in topbar #actions slot */
.mcp-server-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  padding: 0 12px;
  border-radius: var(--r-full, 999px);
  background: var(--surface-2);
  border: 1px solid var(--line);
  font-size: var(--t-small, 12.5px);
  color: var(--text-2);
}
.mcp-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-4);
}
.mcp-dot.online {
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-soft);
}
.mcp-server-name {
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}
.mcp-endpoint {
  font-family: var(--font-mono);
  font-size: var(--t-micro, 11px);
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

.mcp-main {
  padding: 16px 24px 40px;
  background: var(--bg);
  min-height: 100%;
}

/* KPI summary row — 4 stat cards + search */
.mcp-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0;
  border-radius: 0;
  background: transparent;
  border: 0;
  margin-bottom: 20px;
}
.mcp-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
  padding: 16px 18px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  box-shadow: var(--sh-1);
  transition: border-color 0.14s var(--ease), box-shadow 0.14s var(--ease);
}
.mcp-stat:hover {
  border-color: var(--line-strong);
  box-shadow: var(--sh-2);
}
.mcp-stat strong {
  font-size: var(--t-h2, 24px);
  font-weight: var(--fw-bold, 700);
  color: var(--text);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
  line-height: 1.2;
}
.mcp-stat span {
  font-size: 11.5px;
  color: var(--text-3);
  font-weight: var(--fw-medium, 500);
  letter-spacing: 0.01em;
  text-transform: uppercase;
}
.mcp-summary-right { margin-left: auto; }
.mcp-search {
  width: 280px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  font-size: var(--t-body, 14px);
  background: var(--surface);
  color: var(--text);
  outline: none;
  font-family: inherit;
  transition: border-color 0.14s var(--ease), box-shadow 0.14s var(--ease);
}
.mcp-search::placeholder { color: var(--text-4); }
.mcp-search:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
}

/* Category pills */
.mcp-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.mcp-tab {
  padding: 6px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-full, 999px);
  background: var(--surface);
  color: var(--text-2);
  font-size: var(--t-small, 12.5px);
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.14s var(--ease), background 0.14s var(--ease), color 0.14s var(--ease);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.mcp-tab:hover {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  color: var(--brand);
}
.mcp-tab.active {
  background: var(--brand);
  color: var(--text-inverse);
  border-color: var(--brand);
}
.mcp-tab-count {
  font-size: var(--t-micro, 11px);
  padding: 1px 7px;
  border-radius: var(--r-full, 999px);
  background: var(--surface-3);
  color: var(--text-3);
  font-weight: var(--fw-semibold, 600);
  font-variant-numeric: tabular-nums;
}
.mcp-tab:hover .mcp-tab-count {
  background: var(--brand-soft-2);
  color: var(--brand);
}
.mcp-tab.active .mcp-tab-count {
  background: rgba(255, 255, 255, 0.22);
  color: var(--text-inverse);
}

.mcp-state {
  padding: 32px;
  text-align: center;
  color: var(--text-3);
  font-size: var(--t-body, 14px);
}
.mcp-state.error { color: var(--err); }
.mcp-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-4);
  font-size: var(--t-small, 12.5px);
}

/* Tool list grid */
.mcp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
}
.mcp-card {
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: 14px 16px;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: var(--sh-1);
  transition: border-color 0.14s var(--ease), background 0.14s var(--ease), box-shadow 0.14s var(--ease);
}
.mcp-card:hover {
  background: var(--surface-2);
  border-color: var(--line-strong);
  box-shadow: var(--sh-2);
}
.mcp-card.expanded { background: var(--surface-2); }

.mcp-card-header { display: flex; flex-direction: column; gap: 6px; }
.mcp-card-title-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mcp-card-icon {
  width: 36px;
  height: 36px;
  font-size: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--r-2, 6px);
  background: var(--brand-soft);
  color: var(--brand);
  border: 1px solid var(--brand-soft-2);
  flex-shrink: 0;
}
.mcp-card-icon.cat-apaas_introspect {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-soft-2);
}
.mcp-card-icon.cat-doc {
  background: var(--info-soft);
  color: var(--info);
  border-color: var(--brand-soft-2);
}
.mcp-card-icon.cat-app_lifecycle {
  background: var(--warn-soft);
  color: var(--warn);
  border-color: transparent;
}
.mcp-card-icon.cat-env {
  background: var(--ok-soft);
  color: var(--ok);
  border-color: transparent;
}
.mcp-card-name {
  font-family: var(--font-mono);
  font-size: var(--t-body, 14px);
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.005em;
}
.mcp-card-cat {
  font-size: var(--t-micro, 11px);
  color: var(--text-3);
  padding: 2px 8px;
  border-radius: var(--r-2, 6px);
  background: var(--surface-3);
  font-weight: var(--fw-medium, 500);
}
.mcp-card-title {
  font-size: var(--t-small, 12.5px);
  color: var(--text-2);
  line-height: 1.5;
  margin: 0;
}

.mcp-card-params { font-size: var(--t-small, 12.5px); }
.mcp-params-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.mcp-params-label { color: var(--text-3); font-weight: var(--fw-medium, 500); }
.mcp-params-empty { color: var(--text-4); font-style: italic; }
.mcp-param-chip {
  font-family: var(--font-mono);
  font-size: var(--t-micro, 11px);
  padding: 2px 8px;
  border-radius: var(--r-2, 6px);
  background: var(--surface-3);
  color: var(--text-2);
  border: 1px solid transparent;
  font-variant-numeric: tabular-nums;
}
.mcp-param-chip.required {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-soft-2);
  font-weight: var(--fw-semibold, 600);
}
.mcp-param-type { color: var(--text-4); font-weight: var(--fw-regular, 400); }

.mcp-card-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
  border-top: 1px solid var(--line);
  margin-top: 2px;
}
.mcp-expand-btn {
  padding: 4px 8px;
  font-size: var(--t-micro, 11px);
  color: var(--text-3);
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: inherit;
  font-weight: var(--fw-medium, 500);
  transition: color 0.14s var(--ease);
}
.mcp-expand-btn:hover { color: var(--brand); }
.mcp-try-btn {
  padding: 6px 14px;
  font-size: var(--t-micro, 11px);
  color: var(--text-inverse);
  background: var(--brand);
  border: none;
  border-radius: var(--r-2, 6px);
  cursor: pointer;
  font-weight: var(--fw-semibold, 600);
  font-family: inherit;
  letter-spacing: 0.005em;
  transition: background 0.14s var(--ease), box-shadow 0.14s var(--ease);
}
.mcp-try-btn:hover {
  background: var(--brand-hover);
  box-shadow: var(--sh-brand);
}
.mcp-try-btn:active { background: var(--brand-hover); transform: translateY(0.5px); }

/* Try-call modal */
.mcp-try-modal {
  position: fixed;
  inset: 0;
  background: rgba(11, 27, 63, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9000;
  backdrop-filter: blur(4px);
}
.mcp-try-card {
  width: 720px;
  max-width: 92vw;
  max-height: 88vh;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-5, 16px);
  display: flex;
  flex-direction: column;
  box-shadow: var(--sh-5);
  overflow: hidden;
}
.mcp-try-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 18px 22px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.mcp-try-header h3 {
  margin: 0;
  font-size: var(--t-h3, 18px);
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.01em;
}
.mcp-try-header h3 code {
  font-family: var(--font-mono);
  color: var(--brand);
  font-size: var(--t-body, 14px);
  background: var(--brand-soft);
  padding: 2px 8px;
  border-radius: var(--r-2, 6px);
  font-weight: var(--fw-semibold, 600);
  font-variant-numeric: tabular-nums;
}
.mcp-try-header p {
  margin: 4px 0 0;
  font-size: var(--t-small, 12.5px);
  color: var(--text-3);
}
.mcp-try-close {
  background: transparent;
  border: none;
  font-size: 18px;
  color: var(--text-4);
  cursor: pointer;
  padding: 4px;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: var(--r-2, 6px);
  transition: background 0.14s var(--ease), color 0.14s var(--ease);
}
.mcp-try-close:hover {
  background: var(--surface-2);
  color: var(--text);
}
.mcp-try-body {
  padding: 18px 22px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.mcp-try-label {
  font-size: var(--t-small, 12.5px);
  color: var(--text-2);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-weight: var(--fw-medium, 500);
}
.mcp-required-chip {
  font-family: var(--font-mono);
  font-size: var(--t-micro, 11px);
  background: var(--brand-soft);
  color: var(--brand);
  padding: 2px 8px;
  border-radius: var(--r-2, 6px);
  border: 1px solid var(--brand-soft-2);
  font-weight: var(--fw-semibold, 600);
  font-variant-numeric: tabular-nums;
}
.mcp-required-empty { color: var(--text-4); font-style: italic; }
.mcp-try-input {
  width: 100%;
  min-height: 160px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  font-family: var(--font-mono);
  font-size: var(--t-mono, 12px);
  resize: vertical;
  outline: none;
  background: var(--surface-2);
  color: var(--text);
  line-height: 1.6;
  font-variant-numeric: tabular-nums;
  transition: border-color 0.14s var(--ease), box-shadow 0.14s var(--ease);
}
.mcp-try-input:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
  background: var(--surface);
}
.mcp-try-actions { display: flex; gap: 8px; }
.mcp-try-run {
  padding: 8px 22px;
  background: var(--brand);
  color: var(--text-inverse);
  border: none;
  border-radius: var(--r-3, 8px);
  font-weight: var(--fw-semibold, 600);
  font-size: var(--t-body, 14px);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease), box-shadow 0.14s var(--ease);
}
.mcp-try-run:hover:not(:disabled) {
  background: var(--brand-hover);
  box-shadow: var(--sh-brand);
}
.mcp-try-run:disabled { opacity: 0.5; cursor: not-allowed; }
.mcp-try-cancel {
  padding: 8px 16px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  color: var(--text-2);
  font-size: var(--t-body, 14px);
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease), border-color 0.14s var(--ease), color 0.14s var(--ease);
}
.mcp-try-cancel:hover {
  background: var(--surface-3);
  border-color: var(--line-strong);
  color: var(--text);
}
.mcp-try-result {
  border-radius: var(--r-3, 8px);
  overflow: hidden;
  border: 1px solid var(--line);
}
.mcp-try-result-header {
  padding: 8px 14px;
  font-weight: var(--fw-semibold, 600);
  font-size: var(--t-small, 12.5px);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mcp-try-result-header.ok {
  background: var(--ok-soft);
  color: var(--ok);
}
.mcp-try-result-header.err {
  background: var(--err-soft);
  color: var(--err);
}
.mcp-try-cost {
  font-family: var(--font-mono);
  font-weight: var(--fw-regular, 400);
  font-variant-numeric: tabular-nums;
}
.mcp-try-result-body {
  margin: 0;
  padding: 14px 18px;
  font-family: var(--font-mono);
  font-size: var(--t-mono, 12px);
  background: var(--surface-2);
  color: var(--text);
  max-height: 280px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.6;
  font-variant-numeric: tabular-nums;
}

.mcp-desc {
  font-size: var(--t-small, 12.5px);
  color: var(--text-2);
  background: var(--surface-2);
  border-left: 3px solid var(--brand);
  padding: 12px 14px;
  border-radius: var(--r-2, 6px);
  white-space: pre-wrap;
  line-height: 1.65;
  font-family: var(--font-sans);
  margin: 0;
}

.mcp-schema { font-size: var(--t-micro, 11px); }
.mcp-schema summary {
  cursor: pointer;
  color: var(--text-3);
  padding: 4px 0;
  font-weight: var(--fw-medium, 500);
  font-family: inherit;
}
.mcp-schema summary:hover { color: var(--brand); }
.mcp-schema pre {
  background: var(--surface-3);
  color: var(--text);
  padding: 12px 14px;
  border-radius: var(--r-2, 6px);
  overflow-x: auto;
  font-size: var(--t-micro, 11px);
  line-height: 1.6;
  font-family: var(--font-mono);
  border: 1px solid var(--line);
  font-variant-numeric: tabular-nums;
}

/* Dark theme — tokens already auto-swap via v3-tokens.css.
   These remaining overrides keep parity with v2 dark experience
   where the v2 styles diverged from the auto-swap. */
:global(html[data-theme="dark"]) .mcp-try-modal {
  background: rgba(0, 0, 0, 0.55);
}
:global(html[data-theme="dark"]) .mcp-schema pre {
  background: var(--surface-3);
}
</style>

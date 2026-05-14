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

      <div v-if="loading" class="mcp-state">加载中…</div>
      <div v-else-if="error" class="mcp-state error">{{ error }}</div>

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
          <span>没匹配的工具</span>
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
                  {{ categoryIcon(tool.category_key) }}
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

            <button
              v-if="tool.description"
              class="mcp-expand-btn"
              @click="expanded[tool.name] = !expanded[tool.name]"
            >
              {{ expanded[tool.name] ? '收起描述 ▲' : '展开详情 ▼' }}
            </button>

            <pre v-if="expanded[tool.name] && tool.description" class="mcp-desc">{{ tool.description }}</pre>

            <details v-if="expanded[tool.name]" class="mcp-schema">
              <summary>JSON Schema</summary>
              <pre>{{ JSON.stringify(tool.input_schema, null, 2) }}</pre>
            </details>
          </article>
        </section>
      </template>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
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
    apaas_introspect: '🔍',
    doc: '📋',
    app_lifecycle: '🚀',
    env: '🌐',
    other: '🔧',
  }[key] || '🔧'
}

onMounted(async () => {
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
})
</script>

<style scoped>
.mcp-server-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(116, 128, 171, 0.08);
  font-size: 12px;
}
.mcp-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d0d4dc;
}
.mcp-dot.online { background: #67c23a; box-shadow: 0 0 4px rgba(103, 194, 58, 0.6); }
.mcp-server-name { font-weight: 600; }
.mcp-endpoint { font-family: ui-monospace, Menlo, monospace; font-size: 11px; color: #777; }

.mcp-main { padding: 16px 24px 40px; }
.mcp-summary {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 18px 20px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.06), rgba(139, 92, 246, 0.04));
  border: 1px solid rgba(99, 102, 241, 0.12);
  margin-bottom: 20px;
}
.mcp-stat { display: flex; flex-direction: column; gap: 2px; }
.mcp-stat strong { font-size: 22px; font-weight: 700; color: #1f2937; }
.mcp-stat span { font-size: 12px; color: #6b7280; }
.mcp-summary-right { margin-left: auto; }
.mcp-search {
  width: 280px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid #e1e4ec;
  border-radius: 8px;
  font-size: 13px;
  background: #fff;
  outline: none;
  transition: border-color 0.15s;
}
.mcp-search:focus { border-color: #6366f1; }

.mcp-tabs { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.mcp-tab {
  padding: 6px 14px;
  border: 1px solid #e1e4ec;
  border-radius: 999px;
  background: #fff;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.mcp-tab:hover { border-color: #c7c9d1; }
.mcp-tab.active { background: #6366f1; color: white; border-color: #6366f1; }
.mcp-tab-count {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.08);
  font-weight: 600;
}
.mcp-tab.active .mcp-tab-count { background: rgba(255, 255, 255, 0.25); }

.mcp-state { padding: 32px; text-align: center; color: #888; }
.mcp-state.error { color: #d32f2f; }
.mcp-empty { padding: 24px; text-align: center; color: #aaa; font-size: 13px; }

.mcp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 14px;
}
.mcp-card {
  border: 1px solid #e1e4ec;
  border-radius: 10px;
  padding: 14px 16px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.15s;
}
.mcp-card:hover { border-color: #c7c9d1; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
.mcp-card.expanded { background: #fafbfc; }

.mcp-card-header { display: flex; flex-direction: column; gap: 4px; }
.mcp-card-title-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mcp-card-icon {
  width: 22px;
  height: 22px;
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: #f3f4f6;
}
.mcp-card-icon.cat-apaas_introspect { background: rgba(139, 92, 246, 0.12); }
.mcp-card-icon.cat-doc { background: rgba(99, 102, 241, 0.12); }
.mcp-card-icon.cat-app_lifecycle { background: rgba(245, 158, 11, 0.12); }
.mcp-card-icon.cat-env { background: rgba(34, 197, 94, 0.12); }
.mcp-card-name {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}
.mcp-card-cat {
  font-size: 11px;
  color: #6b7280;
  padding: 1px 6px;
  border-radius: 4px;
  background: #f3f4f6;
}
.mcp-card-title {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.45;
  margin: 0;
}

.mcp-card-params { font-size: 12px; }
.mcp-params-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.mcp-params-label { color: #6b7280; }
.mcp-params-empty { color: #c0c2cb; font-style: italic; }
.mcp-param-chip {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: #f3f4f6;
  color: #4b5563;
}
.mcp-param-chip.required {
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  font-weight: 600;
}
.mcp-param-type { color: #9ca3af; font-weight: 400; }

.mcp-expand-btn {
  align-self: flex-start;
  padding: 4px 8px;
  font-size: 11px;
  color: #6b7280;
  background: none;
  border: none;
  cursor: pointer;
}
.mcp-expand-btn:hover { color: #6366f1; }

.mcp-desc {
  font-size: 12px;
  color: #4b5563;
  background: #fafbfc;
  border-left: 3px solid #6366f1;
  padding: 10px 14px;
  border-radius: 4px;
  white-space: pre-wrap;
  line-height: 1.6;
  font-family: ui-sans-serif, system-ui, -apple-system;
}

.mcp-schema { font-size: 11px; }
.mcp-schema summary { cursor: pointer; color: #6b7280; padding: 4px 0; }
.mcp-schema pre {
  background: #1f2937;
  color: #f9fafb;
  padding: 10px 14px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 11px;
  line-height: 1.5;
}

:global(html[data-theme="dark"]) .mcp-summary { background: linear-gradient(135deg, rgba(99,102,241,0.12), rgba(139,92,246,0.08)); }
:global(html[data-theme="dark"]) .mcp-card { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.08); }
:global(html[data-theme="dark"]) .mcp-card-name { color: rgba(255,255,255,0.92); }
:global(html[data-theme="dark"]) .mcp-card-title { color: rgba(255,255,255,0.7); }
</style>

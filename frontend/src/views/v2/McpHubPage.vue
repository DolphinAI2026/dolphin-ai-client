<!-- frontend/src/views/v2/McpHubPage.vue -->
<!--
  MCP 管理 — Model Context Protocol Hub
  Summary cards + filter tabs + 2-col layout (list / detail).

  Seed data inline (verbatim from $DESIGN_SRC/data.js lines 540-606, 8 servers).
  All action buttons are UI stubs (ElMessage.info) — backend wiring lands in P3.
  See docs/superpowers/plans/2026-05-18-apaas-builder-redesign-p0-p1.md (P2 — Task #11).
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { useMcpStore } from '@/stores/mcp'
import type { McpServer } from '@/api/mcp'

type McpStatus = McpServer['status']
type McpTransport = McpServer['transport']

// Backend store — replaces the inline `MCP_SERVERS` const previously seeded here.
const mcpStore = useMcpStore()
onMounted(() => mcpStore.fetchServers())

// Placeholder tool list — shown verbatim from the design source. Real tool
// schemas will come from `/mcp/tools` once backend wires land.
const SAMPLE_TOOLS: Array<{ name: string; desc: string; params: number }> = [
  { name: 'create_model',       desc: '创建数据模型',       params: 3 },
  { name: 'create_form_config', desc: '生成表单配置',       params: 5 },
  { name: 'save_form_config',   desc: '保存表单配置',       params: 2 },
  { name: 'create_role',        desc: '创建角色',           params: 4 },
  { name: 'list_models',        desc: '列出当前应用模型',   params: 1 },
  { name: 'add_subtable_field', desc: '增加子表字段',       params: 3 },
]

type FilterKey = 'all' | 'connected' | 'error' | 'disabled' | 'official' | 'custom'

const filterKey = ref<FilterKey>('all')
const query = ref('')
const selectedId = ref<string>('')

const filters = computed(() => {
  const list = mcpStore.servers
  return [
    { k: 'all'       as FilterKey, l: '全部',     c: list.length },
    { k: 'connected' as FilterKey, l: '已连接',   c: list.filter(s => s.status === 'connected').length },
    { k: 'error'     as FilterKey, l: '异常',     c: list.filter(s => s.status === 'error').length },
    { k: 'disabled'  as FilterKey, l: '已停用',   c: list.filter(s => s.status === 'disabled').length },
    { k: 'official'  as FilterKey, l: '官方',     c: list.filter(s => s.official).length },
    { k: 'custom'    as FilterKey, l: '自定义',   c: list.filter(s => !s.official).length },
  ]
})

const filtered = computed<McpServer[]>(() => {
  let list = mcpStore.servers.slice()
  if (filterKey.value === 'official')        list = list.filter(s => s.official)
  else if (filterKey.value === 'custom')     list = list.filter(s => !s.official)
  else if (filterKey.value !== 'all')        list = list.filter(s => s.status === filterKey.value)
  const q = query.value.trim().toLowerCase()
  if (q) list = list.filter(s => (s.name + s.code + s.desc).toLowerCase().includes(q))
  return list
})

const current = computed<McpServer | undefined>(
  () => mcpStore.servers.find(s => s.id === selectedId.value) || filtered.value[0]
)

const stats = computed(() => {
  const list = mcpStore.servers
  const connected = mcpStore.connectedCount || list.filter(s => s.status === 'connected').length
  const errored = mcpStore.errorCount || list.filter(s => s.status === 'error').length
  const totalTools = mcpStore.toolsTotal
  const totalUsage = list.reduce((s, m) => s + m.usage, 0)
  return [
    { label: '已连接',     v: String(connected),   tone: 'ok'    as const, icon: 'check' },
    { label: '异常 · 需处理', v: String(errored),  tone: 'warn'  as const, icon: 'bell' },
    { label: '可用工具',   v: String(totalTools),  tone: 'brand' as const, icon: 'zap' },
    { label: '本月调用',   v: totalUsage.toLocaleString(), tone: 'info' as const, icon: 'layers' },
  ]
})

function statusLabel(s: McpStatus): string {
  return s === 'connected' ? '已连接' : s === 'error' ? '异常' : '已停用'
}
function statusBadgeCls(s: McpStatus): string {
  return s === 'connected' ? 'badge-emerald' : s === 'error' ? 'badge-rose' : 'badge-amber'
}

function notImpl(action: string): void {
  ElMessage.info(`${action} 即将上线`)
}

// ─── Icons — copy from $DESIGN_SRC/shell.jsx (subset). ────────────────────
const ICONS: Record<string, string> = {
  check:    '<path d="m5 13 4 4 10-10"/>',
  bell:     '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/>',
  zap:      '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  layers:   '<path d="m12 2 10 6-10 6L2 8z"/><path d="m2 14 10 6 10-6"/>',
  plus:     '<path d="M12 5v14"/><path d="M5 12h14"/>',
  book:     '<path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1 0-4h13"/><path d="M9 7h6"/>',
  refresh:  '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  more:     '<circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="5" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.2" fill="currentColor" stroke="none"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/>',
  search:   '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  gear:     '<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8 2 2 0 1 1-2.8 2.8 1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5 2 2 0 1 1-4 0 1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3 2 2 0 1 1-2.8-2.8 1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1 2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8 2 2 0 1 1 2.8-2.8 1.7 1.7 0 0 0 1.8.3 1.7 1.7 0 0 0 1-1.5 2 2 0 1 1 4 0 1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3 2 2 0 1 1 2.8 2.8 1.7 1.7 0 0 0-.3 1.8 1.7 1.7 0 0 0 1.5 1 2 2 0 1 1 0 4 1.7 1.7 0 0 0-1.5 1z"/>',
}
function renderIcon(name: string, size = 16): string {
  const inner = ICONS[name] || ''
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

<template>
  <WorkbenchShell>
    <div class="page">
      <div class="page-pad">
        <!-- Page head -->
        <div class="page-head">
          <div>
            <h1 class="page-title">
              MCP 管理
              <span class="badge badge-brand" style="margin-left: 8px;">{{ mcpStore.servers.length }} 个</span>
            </h1>
            <div class="page-subtitle">
              Model Context Protocol — AI 工具接入的统一目录。挂载到智能体后，AI 可以调用这些工具。
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-secondary" @click="notImpl('配置')">
              <span class="icon" v-html="renderIcon('gear', 13)" /> 配置
            </button>
            <button class="btn btn-primary" @click="notImpl('添加 MCP 服务器')">
              <span class="icon" v-html="renderIcon('plus', 13)" /> 添加 MCP 服务器
            </button>
          </div>
        </div>

        <!-- Loading state (first paint only — store reactive, hides automatically) -->
        <div v-if="mcpStore.loading && !mcpStore.servers.length" class="mcp-loading">
          加载中...
        </div>

        <!-- Dev mode banner: shown when no servers connected but catalog has entries. -->
        <div
          v-if="!mcpStore.loading && mcpStore.connectedCount === 0 && mcpStore.servers.length > 0"
          class="mcp-dev-banner"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 18a4 4 0 0 0 0-8 6 6 0 0 0-12 1 4 4 0 0 0 0 8z" />
            <path d="M9 12l2 2 4-4" />
          </svg>
          <span>本地 dev 模式无法访问生产 cluster — 显示的 MCP server 是 catalog 占位。生产环境会自动连接 dolphin v2 cluster。</span>
        </div>

        <!-- Summary cards -->
        <div class="mcp-summary">
          <div v-for="s in stats" :key="s.label" class="mcp-summary-card">
            <div :class="['mcp-summary-icon', `mcp-tone-${s.tone}`]" v-html="renderIcon(s.icon, 16)" />
            <div>
              <div class="mcp-summary-v">{{ s.v }}</div>
              <div class="mcp-summary-l">{{ s.label }}</div>
            </div>
          </div>
        </div>

        <!-- Filter + search -->
        <div class="apps-bar" style="margin-top: 20px;">
          <div class="apps-tabs">
            <button
              v-for="f in filters"
              :key="f.k"
              :class="['apps-tab', { active: filterKey === f.k }]"
              @click="filterKey = f.k"
            >
              {{ f.l }}<span class="apps-tab-count">{{ f.c }}</span>
            </button>
          </div>
          <div class="apps-search">
            <span class="icon" v-html="renderIcon('search', 13)" />
            <input v-model="query" placeholder="搜索名称、代号、描述…" />
          </div>
        </div>

        <!-- Two-column: list + detail -->
        <div class="mcp-layout">
          <div class="mcp-list card" style="padding: 0; overflow: hidden;">
            <button
              v-for="m in filtered"
              :key="m.id"
              :class="['mcp-list-item', { active: selectedId === m.id }]"
              @click="selectedId = m.id"
            >
              <div class="mcp-list-item-head">
                <div :class="['mcp-list-status', `mcp-status-${m.status}`]">
                  <span v-if="m.status === 'connected'" class="mcp-list-pulse" />
                </div>
                <div class="mcp-list-name truncate">{{ m.name }}</div>
                <span v-if="m.official" class="badge badge-brand" style="margin-left: auto;">官方</span>
                <span v-else class="badge badge-skip" style="margin-left: auto;">{{ m.tags.includes('第三方') ? '第三方' : '自定义' }}</span>
              </div>
              <div class="mcp-list-meta">
                <span class="mono truncate" :title="m.endpoint">{{ m.endpoint }}</span>
              </div>
              <div v-if="m.status === 'error'" class="mcp-list-error">
                <span class="icon" v-html="renderIcon('bell', 11)" /> {{ m.error }}
              </div>
              <div v-else-if="m.status === 'disabled' && m.error" class="mcp-list-dev-notice">
                {{ m.error }}
              </div>
              <div class="mcp-list-foot">
                <span class="badge badge-outline mono" style="text-transform: uppercase; font-size: 10px;">{{ m.transport }}</span>
                <span style="font-size: 11px; color: var(--text-3);">工具 {{ m.tools }}</span>
                <span class="mcp-list-time">最近 {{ m.last_used || '—' }}</span>
              </div>
            </button>
            <div v-if="filtered.length === 0" class="mcp-empty">
              没有匹配的 MCP 服务器
            </div>
          </div>

          <div v-if="current" class="mcp-detail card">
            <div class="mcp-detail-head">
              <div :class="['mcp-detail-status', `mcp-status-${current.status}`]">
                <span v-if="current.status === 'connected'" class="mcp-list-pulse" />
              </div>
              <div style="flex: 1; min-width: 0;">
                <div class="mcp-detail-title">
                  {{ current.name }}
                  <span v-if="current.official" class="badge badge-brand" style="margin-left: 8px;">官方</span>
                  <span :class="['badge', statusBadgeCls(current.status)]" style="margin-left: 6px;">
                    <span class="badge-dot" />{{ statusLabel(current.status) }}
                  </span>
                </div>
                <div class="mcp-detail-sub">
                  <span class="mono">{{ current.code }}</span>
                  <span>·</span>
                  <span>v{{ current.version }}</span>
                  <span>·</span>
                  <span>本月调用 {{ current.usage }}</span>
                </div>
              </div>
              <div style="display: flex; gap: 6px;">
                <button class="btn btn-secondary btn-sm" @click="notImpl('测试连接')">
                  <span class="icon" v-html="renderIcon('refresh', 12)" /> 测试连接
                </button>
                <button class="btn btn-secondary btn-sm" @click="notImpl('解绑')">解绑</button>
                <button
                  class="icon-btn"
                  style="width: 28px; height: 28px;"
                  @click="notImpl('更多操作')"
                  v-html="renderIcon('more', 14)"
                />
              </div>
            </div>

            <div class="mcp-detail-desc">{{ current.desc }}</div>

            <div v-if="current.status === 'error'" class="mcp-detail-alert">
              <span class="icon" v-html="renderIcon('bell', 14)" />
              <div>
                <div style="font-weight: 600;">{{ current.error }}</div>
                <div style="font-size: 12px; color: var(--text-3); margin-top: 2px;">
                  建议：检查本地 bridge 进程，或切换至备用 endpoint。
                </div>
              </div>
            </div>

            <div v-else-if="current.status === 'disabled'" class="mcp-detail-dev-notice">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <circle cx="12" cy="16" r="0.5" />
              </svg>
              <span>{{ current.error || '本地未接入 v2 MCP cluster' }}</span>
            </div>

            <div class="mcp-detail-grid">
              <div>
                <div class="mcp-detail-label">Endpoint</div>
                <div class="mcp-detail-val mono truncate" :title="current.endpoint">{{ current.endpoint }}</div>
              </div>
              <div>
                <div class="mcp-detail-label">传输</div>
                <div class="mcp-detail-val mono" style="text-transform: uppercase;">{{ current.transport }}</div>
              </div>
              <div>
                <div class="mcp-detail-label">工具数</div>
                <div class="mcp-detail-val">{{ current.tools }}</div>
              </div>
              <div>
                <div class="mcp-detail-label">版本</div>
                <div class="mcp-detail-val mono">v{{ current.version }}</div>
              </div>
            </div>

            <!-- Tool list -->
            <div class="mcp-detail-section">
              <div class="mcp-detail-section-head">
                <span class="mcp-detail-section-title">
                  暴露的工具
                  <span style="color: var(--text-3); font-weight: 500;">{{ current.tools }}</span>
                </span>
                <button class="section-action" @click="notImpl('查看全部工具')">查看全部 →</button>
              </div>
              <div class="mcp-tools-grid">
                <div
                  v-for="t in SAMPLE_TOOLS.slice(0, Math.min(6, current.tools))"
                  :key="t.name"
                  class="mcp-tool"
                >
                  <div class="mcp-tool-head">
                    <code class="mono mcp-tool-name">{{ t.name }}</code>
                    <span class="mcp-tool-params">{{ t.params }} 参数</span>
                  </div>
                  <div class="mcp-tool-desc">{{ t.desc }}</div>
                </div>
              </div>
            </div>

            <!-- Scope checkboxes -->
            <div class="mcp-detail-section">
              <div class="mcp-detail-section-head">
                <span class="mcp-detail-section-title">允许的调用方</span>
              </div>
              <div class="mcp-scope-row">
                <span class="mcp-scope-chip mcp-scope-on">
                  <span class="icon" v-html="renderIcon('check', 11)" /> AI 对话（智能搭建）
                </span>
                <span class="mcp-scope-chip mcp-scope-on">
                  <span class="icon" v-html="renderIcon('check', 11)" /> 睿鲸 AI Coding
                </span>
                <span class="mcp-scope-chip mcp-scope-off">Vibe Coding 全代码</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Tip strip -->
        <div class="mcp-tip">
          <span class="icon" v-html="renderIcon('book', 14)" />
          <div>
            <b>MCP 是统一 AI 工具接入协议。</b>&nbsp;所有挂载到智能体的工具调用都通过 MCP 安全路由 —
            得帆云 aPaaS Tools 是默认挂载的官方 MCP；自定义 MCP 可挂入飞书 / ERP / 私有知识库等。
          </div>
          <button class="btn btn-secondary btn-sm" @click="notImpl('阅读文档')">
            <span class="icon" v-html="renderIcon('external', 12)" /> 阅读文档
          </button>
        </div>
      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
/* Page chrome — same as RuntimePage / IndustryPage. */
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; flex: 1; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-title {
  font-size: 22px; font-weight: 600; color: var(--text);
  letter-spacing: -0.02em; line-height: 1.2; margin: 0;
  display: inline-flex; align-items: center;
}
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; max-width: 760px; line-height: 1.55; }

.mcp-loading {
  font-size: 13px; color: var(--text-3);
  padding: 18px 0; text-align: center;
}

.mcp-dev-banner {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px;
  background: var(--ai-soft, var(--sky-bg)); color: var(--ai-text, var(--sky));
  border: 1px solid var(--ai-soft-2, var(--sky-bg)); border-radius: 10px;
  margin-bottom: 16px;
  font-size: 12.5px; line-height: 1.55;
}
.mcp-dev-banner svg { flex-shrink: 0; }

.mcp-list-dev-notice {
  font-size: 11.5px; color: var(--text-3);
  background: var(--surface-3); padding: 4px 8px; border-radius: 6px;
  display: inline-flex; align-items: center; gap: 4px;
  margin-left: 18px;
}

.mcp-detail-dev-notice {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px;
  background: var(--surface-3); color: var(--text-3);
  border-left: 3px solid var(--text-4);
  border-radius: 6px;
  margin-top: 12px; font-size: 12px;
}
.mcp-detail-dev-notice svg { flex-shrink: 0; }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  height: 32px; padding: 0 14px; border-radius: 8px;
  font-size: 13px; font-weight: 500; cursor: pointer;
  border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit;
  white-space: nowrap; transition: background 0.12s, border-color 0.12s, box-shadow 0.12s;
}
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; box-shadow: 0 1px 2px rgba(28, 21, 73, 0.16), inset 0 -1px 0 rgba(0, 0, 0, 0.15); }
.btn-primary:hover { background: var(--brand-hover); box-shadow: 0 2px 6px var(--brand-ring); }
.btn-secondary { background: var(--surface); border-color: var(--border-strong); }
.btn-secondary:hover { border-color: var(--text-4); }
.btn .icon { display: inline-flex; align-items: center; }
.btn .icon :deep(svg) { display: block; }

.icon-btn {
  display: inline-grid; place-items: center; width: 24px; height: 24px;
  border-radius: 6px; border: 1px solid transparent; background: transparent;
  color: var(--text-3); cursor: pointer; transition: background 0.14s, color 0.14s;
}
.icon-btn:hover { background: var(--surface-3); color: var(--text); }
.icon-btn :deep(svg) { display: block; }

/* Cards */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); }

/* Section action link */
.section-action {
  background: transparent; border: 0; cursor: pointer;
  color: var(--brand-text); font-size: 12px; font-weight: 500; font-family: inherit;
  padding: 2px 4px; border-radius: 4px;
}
.section-action:hover { color: var(--brand); }

/* Badges */
.badge {
  display: inline-flex; align-items: center; gap: 4px;
  height: 20px; padding: 0 7px; border-radius: 5px;
  font-size: 11px; font-weight: 500;
  background: var(--surface-3); color: var(--text-2);
  border: 1px solid transparent;
}
.badge-brand   { background: var(--brand-soft); color: var(--brand-text); }
.badge-emerald { background: var(--emerald-bg); color: var(--emerald); }
.badge-amber   { background: var(--amber-bg);   color: var(--amber); }
.badge-rose    { background: var(--rose-bg);    color: var(--rose); }
.badge-skip    { background: var(--surface-3);  color: var(--text-3); }
.badge-outline { background: transparent; color: var(--text-3); border-color: var(--border-strong); }
.badge-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.badge .icon { display: inline-flex; align-items: center; }
.badge .icon :deep(svg) { display: block; }

/* ───── Summary strip (.mcp-summary) ───── */
.mcp-summary {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
  margin-top: 4px; margin-bottom: 4px;
}
.mcp-summary-card {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--shadow-xs);
}
.mcp-summary-icon {
  width: 36px; height: 36px; border-radius: 10px;
  display: grid; place-items: center; flex-shrink: 0;
}
.mcp-summary-icon :deep(svg) { display: block; }
.mcp-summary-icon.mcp-tone-ok    { background: var(--emerald-bg); color: var(--emerald); }
.mcp-summary-icon.mcp-tone-warn  { background: var(--rose-bg);    color: var(--rose); }
.mcp-summary-icon.mcp-tone-brand { background: var(--brand-soft); color: var(--brand-text); }
.mcp-summary-icon.mcp-tone-info  { background: var(--ai-soft, var(--sky-bg));   color: var(--ai-text, var(--sky)); }
.mcp-summary-v { font-size: 22px; font-weight: 600; line-height: 1.1; letter-spacing: -0.02em; color: var(--text); }
.mcp-summary-l { font-size: 11.5px; color: var(--text-3); margin-top: 2px; }

/* ───── Filter bar (.apps-bar / .apps-tabs / .apps-search) ───── */
.apps-bar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 16px; flex-wrap: wrap;
}
.apps-tabs {
  display: flex; align-items: center; gap: 2px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 3px;
}
.apps-tab {
  display: inline-flex; align-items: center; gap: 6px;
  height: 28px; padding: 0 12px;
  border: none; background: transparent; border-radius: 7px;
  font-size: 12.5px; font-weight: 500; color: var(--text-2);
  cursor: pointer; font-family: inherit;
  transition: background 0.12s, color 0.12s;
}
.apps-tab:hover { color: var(--text); }
.apps-tab.active {
  background: var(--brand-soft); color: var(--brand-text);
  box-shadow: 0 1px 2px rgba(28, 21, 73, 0.04);
}
.apps-tab-count {
  font-size: 10.5px; font-weight: 600;
  padding: 1px 6px; border-radius: 999px;
  background: var(--surface-3); color: var(--text-3);
}
.apps-tab.active .apps-tab-count { background: var(--brand); color: #fff; }

.apps-search {
  display: flex; align-items: center; gap: 6px;
  height: 32px; padding: 0 10px;
  border: 1px solid var(--border-strong); border-radius: 8px;
  background: var(--surface); width: 240px;
}
.apps-search input {
  flex: 1; border: none; background: transparent; color: var(--text);
  font-size: 12.5px; outline: none; font-family: inherit;
}
.apps-search input::placeholder { color: var(--text-3); }
.apps-search .icon :deep(svg) { color: var(--text-3); display: block; }

/* ───── 2-col layout ───── */
.mcp-layout {
  display: grid; grid-template-columns: 320px 1fr; gap: 14px;
  margin-top: 4px;
}

/* ───── List ───── */
.mcp-list {
  display: flex; flex-direction: column;
  max-height: 720px; overflow-y: auto;
}
.mcp-list-item {
  display: flex; flex-direction: column; gap: 6px;
  padding: 12px 14px;
  border: none; border-bottom: 1px solid var(--border);
  background: transparent; cursor: pointer;
  text-align: left; font-family: inherit;
  transition: background 0.12s;
  position: relative;
}
.mcp-list-item:last-child { border-bottom: none; }
.mcp-list-item:hover { background: var(--surface-2); }
.mcp-list-item.active { background: var(--brand-soft); }
.mcp-list-item.active::before {
  content: ''; position: absolute;
  left: 0; top: 8px; bottom: 8px; width: 3px;
  border-radius: 2px; background: var(--brand);
}
.mcp-list-item-head { display: flex; align-items: center; gap: 8px; }
.mcp-list-status {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--text-4); position: relative; flex-shrink: 0;
}
.mcp-status-connected { background: var(--emerald); }
.mcp-status-error     { background: var(--rose); }
.mcp-status-disabled  { background: var(--text-4); }
.mcp-list-pulse {
  position: absolute; inset: -2px;
  border-radius: 50%;
  border: 2px solid var(--emerald);
  opacity: 0.5;
  animation: mcpPulse 1.8s ease-out infinite;
}
@keyframes mcpPulse {
  0%   { transform: scale(0.9); opacity: 0.6; }
  100% { transform: scale(1.8); opacity: 0; }
}
.mcp-list-name { font-size: 13.5px; font-weight: 600; color: var(--text); flex: 1; min-width: 0; }
.mcp-list-meta {
  display: flex; align-items: center; gap: 6px;
  font-size: 11.5px; color: var(--text-3);
  margin-left: 18px;
}
.mcp-list-error {
  font-size: 11.5px; color: var(--rose);
  background: var(--rose-bg); padding: 4px 8px; border-radius: 6px;
  display: inline-flex; align-items: center; gap: 4px;
  margin-left: 18px;
}
.mcp-list-error .icon :deep(svg) { display: block; }
.mcp-list-foot {
  display: flex; align-items: center; gap: 6px;
  margin-left: 18px;
}
.mcp-list-time { font-size: 11px; color: var(--text-3); margin-left: auto; }
.mcp-empty {
  padding: 28px 16px; text-align: center;
  color: var(--text-3); font-size: 12.5px;
}

/* ───── Detail ───── */
.mcp-detail { padding: 22px; display: flex; flex-direction: column; gap: 18px; }
.mcp-detail-head { display: flex; align-items: center; gap: 12px; }
.mcp-detail-status {
  width: 12px; height: 12px; border-radius: 50%;
  position: relative; flex-shrink: 0;
  background: var(--text-4);
}
.mcp-detail-title {
  font-size: 17px; font-weight: 600; color: var(--text);
  letter-spacing: -0.015em;
  display: flex; align-items: center; flex-wrap: wrap; gap: 2px;
}
.mcp-detail-sub {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-3); margin-top: 4px;
}
.mcp-detail-desc {
  font-size: 13.5px; line-height: 1.6; color: var(--text-2);
}
.mcp-detail-alert {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 12px 14px;
  background: var(--rose-bg);
  border: 1px solid rgba(220, 38, 38, 0.20);
  border-radius: 10px;
  color: var(--rose); font-size: 13px;
}
.mcp-detail-alert .icon :deep(svg) { display: block; }
.mcp-detail-grid {
  display: grid; grid-template-columns: 1.4fr 0.6fr 0.5fr 0.6fr;
  gap: 10px 18px;
  padding: 14px 16px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.mcp-detail-label {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.10em;
  text-transform: uppercase; color: var(--text-3); margin-bottom: 4px;
}
.mcp-detail-val { font-size: 13px; color: var(--text); font-weight: 500; }

.mcp-detail-section { display: flex; flex-direction: column; gap: 10px; }
.mcp-detail-section-head { display: flex; align-items: center; justify-content: space-between; }
.mcp-detail-section-title { font-size: 13px; font-weight: 600; color: var(--text); }

.mcp-tools-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
}
.mcp-tool {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 9px; padding: 9px 12px;
}
.mcp-tool-head { display: flex; align-items: center; gap: 8px; }
.mcp-tool-name {
  font-size: 12.5px; font-weight: 600;
  color: var(--brand-text); background: var(--brand-soft);
  padding: 2px 6px; border-radius: 4px;
}
.mcp-tool-params { font-size: 11px; color: var(--text-3); margin-left: auto; }
.mcp-tool-desc { font-size: 11.5px; color: var(--text-2); margin-top: 4px; }

.mcp-scope-row { display: flex; flex-wrap: wrap; gap: 6px; }
.mcp-scope-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 9px; border-radius: 6px;
  font-size: 11.5px; font-weight: 500;
}
.mcp-scope-chip .icon :deep(svg) { display: block; }
.mcp-scope-on  { background: var(--emerald-bg); color: var(--emerald); }
.mcp-scope-off { background: var(--surface-3); color: var(--text-3); text-decoration: line-through; }

/* ───── Bottom tip strip (info) ───── */
.mcp-tip {
  display: flex; align-items: center; gap: 12px;
  margin-top: 18px; padding: 14px 16px;
  background: var(--ai-soft, var(--sky-bg));
  border: 1px solid var(--ai-soft-2, var(--sky-bg));
  border-radius: 12px;
  font-size: 12.5px; color: var(--text-2); line-height: 1.55;
}
.mcp-tip .icon :deep(svg) { color: var(--ai-text, var(--sky)); display: block; flex-shrink: 0; }
.mcp-tip b { color: var(--text); font-weight: 600; }
.mcp-tip > button { margin-left: auto; flex-shrink: 0; }

.mono { font-family: var(--d-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>

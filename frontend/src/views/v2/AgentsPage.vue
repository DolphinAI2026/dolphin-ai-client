<!-- frontend/src/views/v2/AgentsPage.vue -->
<!--
  Agent Config Center — 3 agents (Builder / Coding / Vibe) with their
  model + System Prompt + Skills + MCP + Knowledge bindings.
  Wired to /api/agents (real backend, lazy-seeds on first read). Model
  dropdown pulls REAL configured models from /api/llm-configs. See
  docs/superpowers/plans/2026-05-18-v2-backend-integration.md (Session 3).
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'
import { useAgentsStore } from '@/stores/agents'
import { llmConfigApi } from '@/api/llmConfig'
import type { AgentConfig as ApiAgentConfig } from '@/api/agents'

interface McpServer {
  id: string
  name: string
  code: string
  status: 'connected' | 'error' | 'disabled'
  tools: number
  version: string
  official: boolean
}
interface IndustryPack {
  id: string
  name: string
  code: string
  tone: 'amber' | 'sky' | 'emerald' | 'rose' | 'brand'
  version: string
  stats: { entities: number; relations: number; workflows: number; dicts: number; forms: number; roles: number }
}

// MCP servers + industry packs — still local stubs until Session 4/5 land
// their own backend tables (these only provide display name/icon/tone for
// the IDs the backend `mcps` / `knowledge.industry_packs` return).
const MCP_SERVERS: McpServer[] = [
  { id: 'mcp-1', name: '得帆云 aPaaS Tools',  code: 'apaas-tools',         status: 'connected', tools: 14, version: '2.3.1', official: true  },
  { id: 'mcp-2', name: '组件市场检索',         code: 'marketplace-search',  status: 'connected', tools: 5,  version: '1.0.4', official: true  },
  { id: 'mcp-3', name: '需求文档检索（飞书）', code: 'feishu-docs',         status: 'connected', tools: 3,  version: '0.4.2', official: false },
  { id: 'mcp-4', name: '内部 ERP 字段映射',    code: 'erp-fields',          status: 'error',     tools: 8,  version: '0.2.0', official: false },
  { id: 'mcp-5', name: '生产工单 SOP 库',      code: 'sop-library',         status: 'disabled',  tools: 6,  version: '0.1.1', official: false },
  { id: 'mcp-6', name: 'GitHub Repo 检索',     code: 'github-search',       status: 'connected', tools: 4,  version: '1.2.0', official: false },
  { id: 'mcp-7', name: '钉钉审批联动',         code: 'dingtalk-approval',   status: 'connected', tools: 7,  version: '0.6.0', official: false },
  { id: 'mcp-8', name: '内部知识库（私有）',   code: 'kb-private',          status: 'connected', tools: 2,  version: '1.5.0', official: false },
]

const INDUSTRY_PACKS: IndustryPack[] = [
  {
    id: 'pkg-mfg', name: '制造装备', code: 'manufacturing', tone: 'amber', version: 'v2.1',
    stats: { entities: 12, relations: 30, workflows: 8, dicts: 24, forms: 18, roles: 6 },
  },
  {
    id: 'pkg-crm', name: '客户运营', code: 'crm-ops', tone: 'sky', version: 'v3.0',
    stats: { entities: 9, relations: 22, workflows: 6, dicts: 18, forms: 14, roles: 5 },
  },
  {
    id: 'pkg-logi', name: '智慧物流', code: 'logistics', tone: 'emerald', version: 'v1.4',
    stats: { entities: 11, relations: 26, workflows: 7, dicts: 21, forms: 15, roles: 5 },
  },
  {
    id: 'pkg-govt', name: '政企服务', code: 'govt-svc', tone: 'rose', version: 'v0.9',
    stats: { entities: 8, relations: 16, workflows: 5, dicts: 36, forms: 12, roles: 6 },
  },
]

const router = useRouter()
const agentsStore = useAgentsStore()

// Fallback empty agent so the template never blows up while the first
// list() request is in-flight (or fails). Once the store has data, `cur`
// resolves to a real row.
const EMPTY_AGENT: ApiAgentConfig = {
  id: 'builder',
  name: '',
  role: '',
  desc: '',
  tone: 'ai',
  icon: 'chat',
  model: '',
  model_options: [],
  system_prompt: '',
  context_window: 200000,
  max_output: 8192,
  active_calls: 0,
  today_calls: 0,
  skills: [],
  mcps: [],
  knowledge: { industry_packs: [], spec_templates: [] },
}

const selectedId = ref<string>('builder')
const cur = computed<ApiAgentConfig>(() => {
  return (
    agentsStore.agents.find(a => a.id === selectedId.value) ||
    agentsStore.agents[0] ||
    EMPTY_AGENT
  )
})

// Local edit state for system_prompt + model (so 重置 can restore + so the
// model <select> persists user choice across re-renders).
const editedPrompt = ref<Record<string, string>>({})
const editedModel = ref<Record<string, string>>({})
const saving = ref(false)

const curPrompt = computed({
  get: () => editedPrompt.value[cur.value.id] ?? cur.value.system_prompt,
  set: (v: string) => { editedPrompt.value[cur.value.id] = v },
})
const curModel = computed({
  get: () => editedModel.value[cur.value.id] ?? cur.value.model,
  set: (v: string) => { editedModel.value[cur.value.id] = v },
})

// Real configured models from /api/llm-configs (Settings → LLM Configs page).
// Prefer the non-admin `/options` endpoint so non-tenant-admin users still see
// the real list; fall back to `list()` (admin only) for richer status info.
const realModels = ref<string[]>([])
async function loadRealModels() {
  const names = new Set<string>()
  try {
    const opts = (await llmConfigApi.listOptions('all')) as unknown as Array<{ model?: string; config_name?: string }>
    if (Array.isArray(opts)) {
      for (const o of opts) {
        if (!o) continue
        if (o.config_name) names.add(o.config_name)
        else if (o.model) names.add(o.model)
      }
    }
  } catch {
    // ignore — fall through to list()
  }
  if (names.size === 0) {
    try {
      const list = (await llmConfigApi.list()) as unknown as Array<{ model?: string; config_name?: string; status?: string }>
      if (Array.isArray(list)) {
        for (const cfg of list) {
          if (!cfg) continue
          if (cfg.status && cfg.status !== 'active') continue
          if (cfg.config_name) names.add(cfg.config_name)
          else if (cfg.model) names.add(cfg.model)
        }
      }
    } catch {
      // silent — falls back to seed model_options.
    }
  }
  realModels.value = Array.from(names)
}

const modelOptions = computed<string[]>(() => {
  const merged = new Set<string>()
  // Always include current value so the select doesn't show empty after PUT.
  if (cur.value.model) merged.add(cur.value.model)
  // Seed options from backend (originally from inline seed).
  for (const m of cur.value.model_options || []) merged.add(m)
  // Real configured models — preferred source going forward.
  for (const m of realModels.value) merged.add(m)
  return Array.from(merged)
})

const curMcps = computed<McpServer[]>(() =>
  cur.value.mcps.map(id => MCP_SERVERS.find(m => m.id === id)).filter(Boolean) as McpServer[]
)
const curPacks = computed<IndustryPack[]>(() =>
  cur.value.knowledge.industry_packs.map(id => INDUSTRY_PACKS.find(p => p.id === id)).filter(Boolean) as IndustryPack[]
)
const curMcpToolsTotal = computed(() => curMcps.value.reduce((s, m) => s + m.tools, 0))

function onReset() {
  delete editedPrompt.value[cur.value.id]
  delete editedModel.value[cur.value.id]
  ElMessage.info('已恢复 System Prompt 与模型初始值')
}
async function onSave() {
  if (!cur.value.id || !agentsStore.agents.length) {
    ElMessage.warning('Agent 列表尚未加载完成')
    return
  }
  if (saving.value) return
  saving.value = true
  try {
    await agentsStore.saveAgent(cur.value.id, {
      model: curModel.value,
      system_prompt: curPrompt.value,
    })
    // Clear local overrides — server is now source of truth.
    delete editedPrompt.value[cur.value.id]
    delete editedModel.value[cur.value.id]
    ElMessage.success('Agent 配置已保存')
  } catch (e: any) {
    ElMessage.error(`保存失败：${e?.message || e}`)
  } finally {
    saving.value = false
  }
}
function onAddSkill() {
  ElMessage.info('Skill 库选择即将上线')
}
function onRemoveSkill(s: { code: string; name: string; desc: string }) {
  ElMessage.info(`Skill「${s.name}」已移除（mock，暂未持久化）`)
}
function onRemoveMcp(m: McpServer) {
  ElMessage.info(`MCP「${m.name}」已解绑（mock，暂未持久化）`)
}
function onRemoveKnowledge(p: IndustryPack) {
  ElMessage.info(`行业包「${p.name}」已移除（mock，暂未持久化）`)
}
function onRemoveSpecTemplate(t: string) {
  ElMessage.info(`SPEC 模板「${t}」已移除（mock，暂未持久化）`)
}
function gotoMcp() { router.push('/mcp') }
function gotoIndustry() { router.push('/industry') }

onMounted(async () => {
  await Promise.all([
    agentsStore.fetchAgents(),
    loadRealModels(),
  ])
  // Default-select first agent if `builder` not present.
  if (agentsStore.agents.length && !agentsStore.agents.find(a => a.id === selectedId.value)) {
    selectedId.value = agentsStore.agents[0].id
  }
})

// Icon set — copy from $DESIGN_SRC/shell.jsx (lines 14-75). Same 24 viewBox /
// 1.6 stroke as RailSidebar. Only the icons this page actually uses.
const ICONS: Record<string, string> = {
  chat:       '<path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z"/>',
  whale:      '<path d="M5 3c-1.5 0-2.2 1.2-2.2 2.4v3l-1.4 1 1.4 1v3.2c0 1.2.7 2.4 2.2 2.4"/><path d="M19 3c1.5 0 2.2 1.2 2.2 2.4v3l1.4 1-1.4 1v3.2c0 1.2-.7 2.4-2.2 2.4"/>',
  code:       '<path d="m9 17-5-5 5-5"/><path d="m15 7 5 5-5 5"/><path d="m13 5-2 14"/>',
  chevronR:   '<path d="m9 6 6 6-6 6"/>',
  sparkle:    '<path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/><path d="M19 17l1 3 3 1-3 1-1 3-1-3-3-1 3-1z"/>',
  refresh:    '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  check:      '<path d="m5 13 4 4 10-10"/>',
  trash:      '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7v13h12V7"/><path d="M10 11v6"/><path d="M14 11v6"/>',
  arrowRight: '<path d="M5 12h14"/><path d="m13 5 7 7-7 7"/>',
  industry:   '<path d="M3 21V11l6-4v4l6-4v4l6-4v14H3z"/><path d="M7 17h2"/><path d="M11 17h2"/><path d="M15 17h2"/>',
  doc:        '<path d="M7 3h8l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h4"/>',
  book:       '<path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1 0-4h13"/><path d="M9 7h6"/>',
}
function renderIcon(name: string, size = 16) {
  const inner = ICONS[name] || ''
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}

const ctxWindowK = computed(() => (cur.value.context_window / 1000).toFixed(0))
const knowledgeEmptyHint = computed(() =>
  cur.value.id === 'whale' ? '组件代码生成基于规范' : 'IDE 内 Agent 基于工程上下文'
)
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="page">
      <div class="page-pad">
        <div class="page-head">
          <div>
            <h1 class="page-title">智能体配置</h1>
            <div class="page-subtitle">
              3 个智能体 = 3 套"脑"，每个有自己的<b>模型 + System Prompt + Skills + MCP + 知识源</b>。
              所有 AI 行为都从这里发起。
            </div>
          </div>
          <button class="btn btn-secondary">
            <span class="icon" v-html="renderIcon('book', 13)" /> Agent 调试历史
          </button>
        </div>

        <div class="agent-layout">
          <!-- Left: 3 agents list -->
          <div class="agent-list">
            <button
              v-for="a in agentsStore.agents"
              :key="a.id"
              class="agent-pick"
              :class="{ active: selectedId === a.id }"
              @click="selectedId = a.id"
            >
              <div :class="['agent-pick-icon', `agent-pick-icon-${a.tone}`]" v-html="renderIcon(a.icon, 18)" />
              <div class="agent-pick-body">
                <div class="agent-pick-name">{{ a.name }}</div>
                <div class="agent-pick-role">{{ a.role }}</div>
                <div class="agent-pick-meta">
                  <span><b>{{ a.skills.length }}</b> Skill</span>
                  <span>·</span>
                  <span><b>{{ a.mcps.length }}</b> MCP</span>
                  <span>·</span>
                  <span>{{ a.today_calls }} 今日调用</span>
                </div>
              </div>
              <span v-if="selectedId === a.id" class="agent-pick-chevron" v-html="renderIcon('chevronR', 14)" />
            </button>
            <div v-if="agentsStore.loading && !agentsStore.agents.length" class="agent-empty">
              加载中…
            </div>

            <div class="agent-help">
              <div class="agent-help-head">
                <span class="icon" v-html="renderIcon('sparkle', 13)" />
                Agent 工作流程
              </div>
              <div class="agent-help-body">
                <div><b>1. 接收</b> 用户输入 + Project 上下文</div>
                <div><b>2. 加载</b> System Prompt + Skills 描述</div>
                <div><b>3. 调用</b> Tool（来自 MCP）+ Knowledge 检索</div>
                <div><b>4. 返回</b> 流式响应 + 调用日志</div>
              </div>
            </div>
          </div>

          <!-- Right: agent detail -->
          <div class="agent-detail">
            <!-- Header card: identity + model + system prompt -->
            <div class="card card-pad">
              <div class="agent-head">
                <div :class="['agent-pick-icon', `agent-pick-icon-${cur.tone}`, 'agent-head-icon']" v-html="renderIcon(cur.icon, 22)" />
                <div class="agent-head-text">
                  <div class="agent-head-name">{{ cur.name }}</div>
                  <div class="agent-head-desc">{{ cur.desc }}</div>
                </div>
                <div class="agent-head-actions">
                  <button class="btn btn-secondary btn-sm" @click="onReset">
                    <span class="icon" v-html="renderIcon('refresh', 12)" /> 重置
                  </button>
                  <button class="btn btn-primary btn-sm" :disabled="saving" @click="onSave">
                    <span class="icon" v-html="renderIcon('check', 12)" /> {{ saving ? '保存中…' : '保存' }}
                  </button>
                </div>
              </div>

              <div class="agent-grid">
                <div class="agent-field">
                  <div class="agent-field-label">模型</div>
                  <select class="input" v-model="curModel">
                    <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
                  </select>
                </div>
                <div class="agent-field">
                  <div class="agent-field-label">上下文窗口</div>
                  <div class="agent-field-value mono">{{ ctxWindowK }}k tokens</div>
                </div>
                <div class="agent-field">
                  <div class="agent-field-label">最大输出</div>
                  <div class="agent-field-value mono">{{ cur.max_output }} tokens</div>
                </div>
              </div>

              <div class="agent-field agent-field-prompt">
                <div class="agent-field-label">System Prompt</div>
                <textarea class="textarea" rows="3" v-model="curPrompt" />
              </div>
            </div>

            <!-- Skills card -->
            <div class="card card-pad">
              <div class="agent-section-head">
                <span>Skills <span class="agent-section-count">{{ cur.skills.length }} 已挂载</span></span>
                <span title="Skill 是带描述的可调用能力包，会作为 system 上下文喂给模型">
                  <span class="term-mark">?</span>
                </span>
                <button class="section-action section-action-trailing" @click="onAddSkill">从 Skill 库添加 →</button>
              </div>
              <div class="agent-skills">
                <div v-for="s in cur.skills" :key="s.code" class="agent-skill">
                  <div class="agent-skill-head">
                    <code class="mono agent-skill-code">{{ s.code }}</code>
                    <span class="agent-skill-name">{{ s.name }}</span>
                    <button class="icon-btn icon-btn-sm" title="移除" @click="onRemoveSkill(s)" v-html="renderIcon('trash', 11)" />
                  </div>
                  <div class="agent-skill-desc">{{ s.desc }}</div>
                </div>
              </div>
            </div>

            <!-- MCPs card -->
            <div class="card card-pad">
              <div class="agent-section-head">
                <span>挂载的 MCP <span class="agent-section-count">{{ curMcps.length }}</span></span>
                <span title="MCP 提供具体可执行工具，模型通过 tool-call 协议调用">
                  <span class="term-mark">?</span>
                </span>
                <button class="section-action section-action-trailing" @click="gotoMcp">MCP 管理 →</button>
              </div>
              <div class="agent-mcps">
                <div v-for="m in curMcps" :key="m.id" class="agent-mcp">
                  <div :class="['mcp-list-status', `mcp-status-${m.status}`]">
                    <span v-if="m.status === 'connected'" class="mcp-list-pulse" />
                  </div>
                  <div class="agent-mcp-body">
                    <div class="agent-mcp-name-row">
                      <span class="agent-mcp-name">{{ m.name }}</span>
                      <span v-if="m.official" class="badge badge-brand">官方</span>
                    </div>
                    <div class="agent-mcp-meta">
                      <span class="mono">{{ m.code }}</span> · {{ m.tools }} 工具 · v{{ m.version }}
                    </div>
                  </div>
                  <button class="icon-btn icon-btn-sm" title="解绑" @click="onRemoveMcp(m)" v-html="renderIcon('trash', 11)" />
                </div>
                <div v-if="curMcps.length === 0" class="agent-empty">此 Agent 暂未挂载任何 MCP</div>
              </div>
            </div>

            <!-- Knowledge card -->
            <div class="card card-pad">
              <div class="agent-section-head">
                <span>知识源
                  <span class="agent-section-count">
                    {{ curPacks.length }} 行业包 + {{ cur.knowledge.spec_templates.length }} 文档模板
                  </span>
                </span>
                <span title="行业包 = 业务对象 / 流程 / 字典；SPEC 模板 = 文档章节骨架">
                  <span class="term-mark">?</span>
                </span>
                <button class="section-action section-action-trailing" @click="gotoIndustry">行业知识库 →</button>
              </div>
              <div v-if="curPacks.length > 0 || cur.knowledge.spec_templates.length > 0" class="agent-knowledge">
                <div v-for="pk in curPacks" :key="pk.id" class="agent-know-row">
                  <div :class="['industry-pack-icon', `tone-${pk.tone}`, 'know-icon']" v-html="renderIcon('industry', 13)" />
                  <div class="agent-know-body">
                    <div class="agent-know-name">
                      {{ pk.name }}
                      <span class="mono agent-know-version">{{ pk.version }}</span>
                    </div>
                    <div class="agent-know-stats">
                      {{ pk.stats.entities }} 业务对象 · {{ pk.stats.workflows }} 流程 · {{ pk.stats.dicts }} 字典
                    </div>
                  </div>
                  <button class="icon-btn icon-btn-sm" title="移除" @click="onRemoveKnowledge(pk)" v-html="renderIcon('trash', 11)" />
                </div>
                <div v-for="t in cur.knowledge.spec_templates" :key="t" class="agent-know-row">
                  <div class="know-icon know-icon-doc" v-html="renderIcon('doc', 13)" />
                  <div class="agent-know-body">
                    <div class="agent-know-name mono">{{ t }}</div>
                    <div class="agent-know-stats">SPEC 模板</div>
                  </div>
                  <button class="icon-btn icon-btn-sm" title="移除" @click="onRemoveSpecTemplate(t)" v-html="renderIcon('trash', 11)" />
                </div>
              </div>
              <div v-else class="agent-empty">
                此 Agent 不使用知识源（{{ knowledgeEmptyHint }}）
              </div>
            </div>

            <!-- Compose flow -->
            <div class="card card-pad agent-compose">
              <div class="agent-section-head"><span>合成流程</span></div>
              <div class="agent-compose-row">
                <span class="agent-compose-chip">用户输入</span>
                <span class="icon" v-html="renderIcon('arrowRight', 11)" />
                <span class="agent-compose-chip">+ Project 上下文</span>
                <span class="icon" v-html="renderIcon('arrowRight', 11)" />
                <span class="agent-compose-chip">+ System Prompt</span>
                <span class="icon" v-html="renderIcon('arrowRight', 11)" />
                <span class="agent-compose-chip">+ {{ cur.skills.length }} Skills 描述</span>
                <span class="icon" v-html="renderIcon('arrowRight', 11)" />
                <span class="agent-compose-chip">→ {{ cur.model }}</span>
                <span class="icon" v-html="renderIcon('arrowRight', 11)" />
                <span class="agent-compose-chip">调用 {{ curMcpToolsTotal }} 工具</span>
                <span class="icon" v-html="renderIcon('arrowRight', 11)" />
                <span class="agent-compose-chip agent-compose-chip-final">流式返回</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
/* Page chrome */
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; flex: 1; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; max-width: 720px; line-height: 1.55; }
.page-subtitle b { color: var(--text); font-weight: 600; }

/* Layout */
.agent-layout { display: grid; grid-template-columns: 320px 1fr; gap: 18px; align-items: flex-start; }

/* Left rail */
.agent-list { display: flex; flex-direction: column; gap: 8px; }
.agent-pick {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--surface); cursor: pointer; text-align: left; font-family: inherit;
  transition: border-color 0.14s, box-shadow 0.14s;
  width: 100%; color: var(--text);
}
.agent-pick:hover { border-color: var(--border-strong); box-shadow: var(--shadow-xs); }
.agent-pick.active { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }
.agent-pick-body { flex: 1; min-width: 0; }
.agent-pick-icon {
  width: 36px; height: 36px; border-radius: 10px;
  display: grid; place-items: center; color: #fff; flex-shrink: 0;
}
.agent-pick-icon :deep(svg) { display: block; }
.agent-pick-icon-ai      { background: linear-gradient(135deg, var(--ai-300), var(--ai-500)); }
.agent-pick-icon-brand   { background: linear-gradient(135deg, var(--brand-400), var(--brand-600)); }
.agent-pick-icon-emerald { background: linear-gradient(135deg, #34D399, #10A37F); }
.agent-pick-name { font-size: 13.5px; font-weight: 600; color: var(--text); }
.agent-pick-role { font-size: 11.5px; color: var(--text-3); margin-top: 2px; }
.agent-pick-meta { display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; color: var(--text-3); }
.agent-pick-meta b { color: var(--text); font-weight: 600; }
.agent-pick-chevron { color: var(--text-3); display: inline-flex; align-items: center; flex-shrink: 0; }

.agent-help {
  background: var(--surface-2); border: 1px dashed var(--border-strong); border-radius: 10px;
  padding: 12px 14px; margin-top: 6px;
}
.agent-help-head { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text); }
.agent-help-body { font-size: 11.5px; color: var(--text-2); line-height: 1.7; margin-top: 6px; }
.agent-help-body b { color: var(--text); font-weight: 600; }

/* Right detail */
.agent-detail { display: flex; flex-direction: column; gap: 18px; min-width: 0; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); }
.card-pad { padding: 18px; }

.agent-head { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 14px; }
.agent-head-icon { width: 44px; height: 44px; border-radius: 12px; }
.agent-head-text { flex: 1; min-width: 0; }
.agent-head-name { font-size: 18px; font-weight: 600; color: var(--text); letter-spacing: -0.015em; }
.agent-head-desc { font-size: 13px; color: var(--text-2); margin-top: 2px; line-height: 1.55; }
.agent-head-actions { display: flex; gap: 4px; flex-shrink: 0; }

.agent-grid { display: grid; grid-template-columns: 1.5fr 1fr 1fr; gap: 12px; }
.agent-field-label {
  font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
  color: var(--text-3); text-transform: uppercase; margin-bottom: 4px;
}
.agent-field-value {
  font-size: 13px; color: var(--text); padding: 8px 12px;
  border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2);
}
.agent-field-prompt { margin-top: 14px; }

/* Form primitives */
.input {
  width: 100%; height: 34px; padding: 0 10px;
  border: 1px solid var(--border); border-radius: 8px; background: var(--surface);
  color: var(--text); font-size: 13px; font-family: inherit;
  outline: none; transition: border-color 0.14s, box-shadow 0.14s;
}
.input:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }
.textarea {
  width: 100%; padding: 8px 10px;
  border: 1px solid var(--border); border-radius: 8px; background: var(--surface);
  color: var(--text); font-size: 13px; font-family: inherit; line-height: 1.55;
  resize: vertical; outline: none; transition: border-color 0.14s, box-shadow 0.14s;
}
.textarea:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  height: 32px; padding: 0 14px; border-radius: 8px;
  font-size: 13px; font-weight: 500; cursor: pointer;
  border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit;
  transition: background 0.14s, border-color 0.14s;
}
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-primary:hover { background: var(--brand-hover); }
.btn-secondary { background: var(--surface); border-color: var(--border-strong); }
.btn-secondary:hover { border-color: var(--text-4); }
.btn .icon { display: inline-flex; align-items: center; }
.btn .icon :deep(svg) { display: block; }

.icon-btn {
  display: inline-grid; place-items: center; width: 24px; height: 24px;
  border-radius: 6px; border: 1px solid transparent; background: transparent;
  color: var(--text-3); cursor: pointer; transition: background 0.14s, color 0.14s;
  margin-left: auto;
}
.icon-btn:hover { background: var(--surface-3); color: var(--text); }
.icon-btn :deep(svg) { display: block; }
.icon-btn-sm { width: 24px; height: 24px; }

/* Section heads */
.agent-section-head {
  display: flex; align-items: center; gap: 6px;
  font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 12px;
}
.agent-section-count { color: var(--text-3); font-weight: 500; }
.section-action {
  margin-left: auto; background: transparent; border: 0; cursor: pointer;
  color: var(--brand-text); font-size: 12px; font-weight: 500; font-family: inherit;
  padding: 2px 4px; border-radius: 4px;
}
.section-action:hover { color: var(--brand); }
.section-action-trailing { margin-left: auto; }

.term-mark {
  display: inline-grid; place-items: center; width: 14px; height: 14px;
  border-radius: 50%; background: var(--surface-3); color: var(--text-3);
  font-size: 9px; font-weight: 700; cursor: help;
}

/* Skills list */
.agent-skills { display: flex; flex-direction: column; gap: 8px; }
.agent-skill { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.agent-skill-head { display: flex; align-items: center; gap: 8px; }
.agent-skill-code {
  background: var(--code-bg); color: var(--code-text);
  padding: 1px 6px; border-radius: 4px; font-size: 10.5px;
}
.agent-skill-name { font-size: 12.5px; font-weight: 600; color: var(--text); }
.agent-skill-desc { font-size: 11.5px; color: var(--text-2); margin-top: 4px; line-height: 1.55; }

/* MCP rows */
.agent-mcps { display: flex; flex-direction: column; gap: 8px; }
.agent-mcp {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2);
}
.agent-mcp-body { flex: 1; min-width: 0; }
.agent-mcp-name-row { display: flex; align-items: center; gap: 6px; }
.agent-mcp-name { font-size: 13px; font-weight: 600; color: var(--text); }
.agent-mcp-meta { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.mcp-list-status {
  width: 8px; height: 8px; border-radius: 50%; position: relative;
  flex-shrink: 0; margin-top: 6px;
}
.mcp-status-connected { background: var(--emerald); }
.mcp-status-error     { background: var(--rose); }
.mcp-status-disabled  { background: var(--text-4); }
.mcp-list-pulse {
  position: absolute; inset: -4px; border-radius: 50%;
  background: var(--emerald); opacity: 0.3; animation: mcpPulse 1.6s infinite;
}
@keyframes mcpPulse {
  0%   { transform: scale(0.7); opacity: 0.5; }
  100% { transform: scale(1.4); opacity: 0; }
}

/* Knowledge rows */
.agent-knowledge { display: flex; flex-direction: column; gap: 8px; }
.agent-know-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2);
}
.agent-know-body { flex: 1; min-width: 0; }
.agent-know-name { font-size: 12.5px; font-weight: 600; color: var(--text); }
.agent-know-version { font-size: 10.5px; color: var(--text-3); font-weight: 500; margin-left: 4px; }
.agent-know-stats { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.know-icon {
  width: 28px; height: 28px; border-radius: 7px;
  display: grid; place-items: center; color: #fff; flex-shrink: 0;
}
.know-icon :deep(svg) { display: block; }
.know-icon-doc { background: var(--surface-3); color: var(--text-2); }
.industry-pack-icon.tone-amber   { background: linear-gradient(135deg, #FBBF24, #D97706); }
.industry-pack-icon.tone-sky     { background: linear-gradient(135deg, #38BDF8, #0284C7); }
.industry-pack-icon.tone-emerald { background: linear-gradient(135deg, #34D399, #10A37F); }
.industry-pack-icon.tone-rose    { background: linear-gradient(135deg, #F87171, #DC2626); }
.industry-pack-icon.tone-brand   { background: linear-gradient(135deg, var(--brand-400), var(--brand-600)); }

.agent-empty {
  padding: 12px; color: var(--text-3); font-size: 12px; text-align: center;
}

/* Compose flow */
.agent-compose { background: var(--surface-2); }
.agent-compose-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; color: var(--text-4); }
.agent-compose-row .icon { display: inline-flex; align-items: center; color: var(--text-4); }
.agent-compose-row .icon :deep(svg) { display: block; }
.agent-compose-chip {
  padding: 4px 10px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 999px; font-size: 11.5px; color: var(--text-2); white-space: nowrap;
}
.agent-compose-chip-final { background: var(--brand-soft); color: var(--brand-text); border-color: transparent; }

/* Badges */
.badge {
  display: inline-flex; align-items: center; gap: 4px;
  height: 18px; padding: 0 6px; border-radius: 4px;
  font-size: 10.5px; font-weight: 500; background: var(--surface-3); color: var(--text-2);
  border: 1px solid transparent;
}
.badge-brand { background: var(--brand-soft); color: var(--brand-text); }

.mono { font-family: var(--d-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
</style>

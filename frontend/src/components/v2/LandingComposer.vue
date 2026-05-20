<!-- frontend/src/components/v2/LandingComposer.vue
  Centered 4-mode composer for the v2 Landing page.
  Emits `tool-click` so the parent can wire mode-specific tool buttons
  (e.g. file-picker for builder) without coupling the composer to stores.
  The `db` mode is the存量 DB 快速接入入口 — 跳 /quick-db wizard，不走文本对话。
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

type Mode = 'builder' | 'coding' | 'vibe' | 'db'
const MODES: { id: Mode; label: string; sub: string; tone: 'ai' | 'brand' | 'emerald' | 'amber' }[] = [
  { id: 'builder', label: 'AI 对话',          sub: '描述需求 → SPEC → 部署',           tone: 'ai' },
  { id: 'db',      label: 'DB 问数',          sub: '给个数据库 → 自动建 CRUD + 问数',  tone: 'amber' },
  { id: 'coding',  label: '睿鲸 AI Coding',   sub: '聊天驱动生成低代码组件',           tone: 'brand' },
  { id: 'vibe',    label: 'Vibe Coding',     sub: '浏览器 VS Code 全代码 + AI 协助',  tone: 'emerald' },
]

const mode = ref<Mode>('builder')
const text = ref('')
const router = useRouter()

const emit = defineEmits<{
  (e: 'tool-click', mode: Mode): void
}>()

const placeholder = computed(() => ({
  builder: '说说你想做什么。例：管理我们部门 200 台设备的领用、归还和报废…',
  db:      '一句话描述你这个库是什么系统（让 AI 推断字段语义）。例：这是一套 ERP 财务模块的只读副本…',
  coding:  '描述要生成的低代码组件或页面。例：做一个支持多选 + 异步加载的客户树组件…',
  vibe:    '描述你想做的代码任务，进入 Vibe Coding 工作区继续。',
}[mode.value]))
const cta = computed(() => ({ builder: '开始对话', db: '填入数据库连接 →', coding: '开始生成', vibe: '打开工作区' }[mode.value]))

function submit() {
  if (mode.value === 'db') {
    // db 模式：text 是"业务描述"（可空），直接跳 wizard 第 1 步
    router.push({ path: '/quick-db', query: text.value.trim() ? { hint: text.value.trim() } : {} })
    return
  }
  if (!text.value.trim()) return
  if (mode.value === 'builder') router.push({ path: '/ai-chat', query: { mode: 'requirements', prompt: text.value } })
  else if (mode.value === 'coding') router.push({ path: '/coding', query: { prompt: text.value } })
  else router.push({ path: '/vibe-coding', query: { prompt: text.value } })
}
</script>

<template>
  <div class="composer">
    <div class="composer-modes">
      <button v-for="m in MODES" :key="m.id" class="mode-pill" :class="['tone-' + m.tone, { active: mode === m.id }]" @click="mode = m.id">
        <div class="mode-pill-label">{{ m.label }}</div>
        <div class="mode-pill-sub">{{ m.sub }}</div>
      </button>
    </div>
    <div class="composer-card" :data-tone="MODES.find(m => m.id === mode)?.tone">
      <div class="composer-strip" />
      <textarea v-model="text" class="composer-input" :placeholder="placeholder" rows="3" />
      <div class="composer-foot">
        <div class="composer-tools">
          <button v-if="mode === 'builder'" class="btn btn-ghost btn-sm" @click="emit('tool-click', 'builder')">📎 上传 .md 文档</button>
          <button v-if="mode === 'db'"      class="btn btn-ghost btn-sm" @click="emit('tool-click', 'db')">🗄️ MySQL / PostgreSQL / Oracle</button>
          <button v-if="mode === 'coding'"  class="btn btn-ghost btn-sm" @click="emit('tool-click', 'coding')">🔌 选择 MCP</button>
          <button v-if="mode === 'vibe'"    class="btn btn-ghost btn-sm" @click="emit('tool-click', 'vibe')">📁 选择仓库</button>
        </div>
        <button class="btn btn-primary" :disabled="mode !== 'db' && !text.trim()" @click="submit">{{ cta }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.composer { width: 100%; max-width: 820px; margin: 0 auto; }
.composer-modes { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
@media (max-width: 720px) { .composer-modes { grid-template-columns: repeat(2, 1fr); } }
.mode-pill { padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); cursor: pointer; font-family: inherit; text-align: left; transition: border-color 0.14s, box-shadow 0.14s, background 0.14s; }
.mode-pill-label { font-size: 13.5px; font-weight: 600; color: var(--text); letter-spacing: -0.005em; }
.mode-pill-sub { font-size: 11.5px; color: var(--text-3); margin-top: 3px; }
.mode-pill.active { border-color: currentColor; box-shadow: 0 0 0 3px var(--ring, var(--brand-ring)); }
.mode-pill.tone-ai.active     { color: var(--ai-text);   background: var(--ai-soft);    --ring: var(--ai-ring); }
.mode-pill.tone-amber.active  { color: var(--amber);     background: var(--amber-bg);   --ring: rgba(245, 158, 11, 0.2); }
.mode-pill.tone-brand.active  { color: var(--brand-text); background: var(--brand-soft); --ring: var(--brand-ring); }
.mode-pill.tone-emerald.active{ color: var(--emerald);    background: var(--emerald-bg);--ring: rgba(16, 163, 127, 0.2); }
.composer-card { position: relative; background: var(--surface); border: 1px solid var(--border-strong); border-radius: 16px; box-shadow: var(--shadow-md); overflow: hidden; }
.composer-strip { height: 3px; }
.composer-card[data-tone="ai"] .composer-strip      { background: var(--ai); }
.composer-card[data-tone="amber"] .composer-strip   { background: var(--amber); }
.composer-card[data-tone="brand"] .composer-strip   { background: var(--brand); }
.composer-card[data-tone="emerald"] .composer-strip { background: var(--emerald); }
.composer-input { width: 100%; min-height: 84px; padding: 14px 16px; border: none; outline: none; resize: none; background: transparent; color: var(--text); font-size: 14px; line-height: 1.55; font-family: inherit; }
.composer-foot { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px 12px; gap: 8px; }
.composer-tools { display: flex; gap: 6px; }
.btn { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit; transition: background 0.12s, border-color 0.12s; }
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary:not(:disabled):hover { background: var(--brand-hover); }
.btn-ghost { color: var(--text-2); }
.btn-ghost:hover { background: var(--surface-2); color: var(--text); }
</style>

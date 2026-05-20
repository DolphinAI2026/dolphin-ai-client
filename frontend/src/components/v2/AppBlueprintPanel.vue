<!-- frontend/src/components/v2/AppBlueprintPanel.vue
     Right-column SPEC blueprint panel for ChatPage v2 redesign.
     Receives parsed SPEC slices as props; emits 'deploy' when user clicks
     the deploy CTA. No business logic / no API calls. -->
<script setup lang="ts">
import { computed, ref } from 'vue'

interface SpecModelField { name: string; code: string; type: string; required?: boolean; unique?: boolean; isNew?: boolean }
interface SpecModel { name: string; code: string; fields: SpecModelField[] }
interface SpecFormSection { title: string; fields: string[] }
interface SpecForm  { name: string; backingModel: string; sections: SpecFormSection[] }
interface SpecFlowNode { role: string; action: string; sla?: string }
interface SpecFlow  { name: string; trigger: string; nodes: SpecFlowNode[] }
interface SpecRole  { name: string; scope: string }
interface SpecDictEntry { code: string; label: string }
interface SpecDict  { name: string; entries: SpecDictEntry[] }

const props = defineProps<{
  models: SpecModel[]
  forms: SpecForm[]
  flows: SpecFlow[]
  roles: SpecRole[]
  dicts: SpecDict[]
  industryPackName?: string | null
  industryObjectCount?: number
}>()
const emit = defineEmits<{ (e: 'deploy'): void }>()

const open = ref<Record<string, boolean>>({
  models: true,
  forms: true,
  flows: false,
  roles: false,
  dicts: false,
})

const counts = computed(() => ({
  models: props.models.length,
  forms: props.forms.length,
  flows: props.flows.length,
  roles: props.roles.length,
  dicts: props.dicts.length,
  fields: props.models.reduce((acc, m) => acc + (Array.isArray(m.fields) ? m.fields.length : 0), 0),
}))

function toggle(k: string) { open.value[k] = !open.value[k] }
</script>

<template>
  <aside class="blueprint">
    <div v-if="industryPackName" class="bp-knowledge">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <path d="M3 21V11l6-4v4l6-4v4l6-4v14H3z" />
      </svg>
      <span>本会话引用 <b>{{ industryPackName }}</b><span v-if="industryObjectCount"> ({{ industryObjectCount }} 业务对象)</span></span>
      <button class="bp-knowledge-link" @click="$router.push('/agents')">查看 Agent 配置 →</button>
    </div>

    <div class="bp-head">
      <div class="bp-title">应用蓝图</div>
      <div class="bp-stats">
        <span><b>{{ counts.models }}</b> 模型</span><span>·</span>
        <span><b>{{ counts.forms }}</b> 表单</span><span>·</span>
        <span><b>{{ counts.flows }}</b> 流程</span><span>·</span>
        <span><b>{{ counts.roles }}</b> 角色</span><span>·</span>
        <span><b>{{ counts.dicts }}</b> 字典</span><span>·</span>
        <span><b>{{ counts.fields }}</b> 字段</span>
      </div>
      <button class="btn btn-primary btn-sm" @click="emit('deploy')">🚀 部署到平台</button>
    </div>

    <div class="bp-scroll">
      <section class="bp-section">
        <button class="bp-section-head" :aria-expanded="open.models" @click="toggle('models')">
          <span>数据模型 <span class="muted">({{ counts.models }})</span></span>
          <svg :class="{ rot: open.models }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </button>
        <div v-show="open.models" class="bp-section-body">
          <div v-if="!models.length" class="bp-empty">暂无模型</div>
          <div v-for="m in models" :key="m.code" class="bp-card">
            <div class="bp-card-head">
              <span class="bp-card-name">{{ m.name }}</span>
              <span class="badge badge-outline mono">{{ m.code }}</span>
            </div>
            <div class="bp-fields">
              <div v-for="f in m.fields" :key="f.code" class="bp-field" :class="{ 'is-new': f.isNew }">
                <span class="bp-field-name">{{ f.name }}</span>
                <span class="bp-field-code mono">{{ f.code }}</span>
                <span class="bp-field-type mono">{{ f.type }}</span>
                <span v-if="f.required" class="badge badge-amber">必填</span>
                <span v-if="f.unique" class="badge badge-brand">唯一</span>
                <span v-if="f.isNew" class="badge badge-brand">NEW</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="bp-section">
        <button class="bp-section-head" :aria-expanded="open.forms" @click="toggle('forms')">
          <span>表单 <span class="muted">({{ counts.forms }})</span></span>
          <svg :class="{ rot: open.forms }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </button>
        <div v-show="open.forms" class="bp-section-body">
          <div v-if="!forms.length" class="bp-empty">暂无表单</div>
          <div v-for="f in forms" :key="f.name" class="bp-card">
            <div class="bp-card-head">
              <span class="bp-card-name">{{ f.name }}</span>
              <span class="bp-card-meta mono">← {{ f.backingModel }}</span>
            </div>
            <div v-for="sec in f.sections" :key="sec.title" class="bp-form-section">
              <div class="bp-form-section-title">{{ sec.title }}</div>
              <div class="bp-form-fields">{{ sec.fields.join(' · ') }}</div>
            </div>
          </div>
        </div>
      </section>

      <section class="bp-section">
        <button class="bp-section-head" :aria-expanded="open.flows" @click="toggle('flows')">
          <span>流程 <span class="muted">({{ counts.flows }})</span></span>
          <svg :class="{ rot: open.flows }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </button>
        <div v-show="open.flows" class="bp-section-body">
          <div v-if="!flows.length" class="bp-empty">暂无流程</div>
          <div v-for="fl in flows" :key="fl.name" class="bp-card">
            <div class="bp-card-head">
              <span class="bp-card-name">{{ fl.name }}</span>
              <span class="bp-card-meta">触发：{{ fl.trigger }}</span>
            </div>
            <div class="bp-flow-chain">{{ fl.nodes.map(n => n.role + ' → ' + n.action).join('  →  ') }}</div>
          </div>
        </div>
      </section>

      <section class="bp-section">
        <button class="bp-section-head" :aria-expanded="open.roles" @click="toggle('roles')">
          <span>角色 <span class="muted">({{ counts.roles }})</span></span>
          <svg :class="{ rot: open.roles }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </button>
        <div v-show="open.roles" class="bp-section-body">
          <div v-if="!roles.length" class="bp-empty">暂无角色</div>
          <div v-for="r in roles" :key="r.name" class="bp-card">
            <div class="bp-card-head">
              <span class="bp-card-name">{{ r.name }}</span>
              <span class="bp-card-meta">范围：{{ r.scope }}</span>
            </div>
          </div>
        </div>
      </section>

      <section class="bp-section">
        <button class="bp-section-head" :aria-expanded="open.dicts" @click="toggle('dicts')">
          <span>字典 <span class="muted">({{ counts.dicts }})</span></span>
          <svg :class="{ rot: open.dicts }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </button>
        <div v-show="open.dicts" class="bp-section-body">
          <div v-if="!dicts.length" class="bp-empty">暂无字典</div>
          <div v-for="d in dicts" :key="d.name" class="bp-card">
            <div class="bp-card-head"><span class="bp-card-name">{{ d.name }}</span></div>
            <div class="bp-dict">{{ d.entries.map(e => e.label + '(' + e.code + ')').join(' · ') }}</div>
          </div>
        </div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Preserved (don't change):
     - 420px panel width / flex layout / border-left structure
     - All class names (template references)
     - Section toggle SVG rotation animation
   Refreshed:
     - All hex purples (#5b5bd6 etc.) gone — pure v3 token cascade
     - --border → --line (intent)
     - radii 8/10 → --r-3/--r-4 token scale
     - Card hover: subtle --sh-2 lift + brand-ring border
     - Title 14 → 14.5 + letter-spacing -0.005em (matches v3 ShellTopBar)
     - Body sizes tightened to v3 scale (12.5 / 12 / 11)
     - Font weights 4 档: 700 (card name) / 600 (title) / 500 (meta) / 400
     - Mono → var(--font-mono) (was --d-font-mono, undefined)
     - Transition uses var(--ease) 0.14s
*/
.blueprint {
  width: 420px;
  flex-shrink: 0;
  background: var(--surface);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.bp-knowledge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--brand-soft);
  color: var(--brand-text);
  font-size: 12px;
  border-bottom: 1px solid var(--line);
}
.bp-knowledge b { color: var(--brand-text); font-weight: var(--fw-semibold, 600); }
.bp-knowledge-link {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--brand);
  font-size: 11.5px;
  cursor: pointer;
  font-family: inherit;
  transition: color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.bp-knowledge-link:hover { color: var(--brand-hover); }

.bp-head {
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bp-title {
  font-size: 14.5px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.005em;
}
.bp-stats {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-3);
  flex-wrap: wrap;
}
.bp-stats b { color: var(--text); font-weight: var(--fw-semibold, 600); }

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: var(--r-3, 8px);
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.btn-sm {
  height: 28px;
  padding: 0 12px;
  font-size: 12px;
  border-radius: var(--r-2, 6px);
  align-self: flex-end;
}
.btn-primary {
  background: var(--brand);
  color: var(--text-inverse, #fff);
  box-shadow: var(--sh-brand);
}
.btn-primary:hover { background: var(--brand-hover); }
.btn-primary:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.bp-scroll { flex: 1; overflow-y: auto; padding: 10px; }
.bp-section { margin-bottom: 4px; }
.bp-section-head {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: var(--r-2, 6px);
  background: transparent;
  border: none;
  color: var(--text);
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
  font-family: inherit;
  letter-spacing: -0.005em;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.bp-section-head:hover {
  background: var(--brand-soft);
  color: var(--brand);
}
.bp-section-head .muted { color: var(--text-3); font-weight: var(--fw-medium, 500); }
.bp-section-head svg { transition: transform 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)); }
.bp-section-head svg.rot { transform: rotate(180deg); }
.bp-section-body { padding: 4px 6px 8px; display: flex; flex-direction: column; gap: 8px; }
.bp-empty {
  font-size: 11.5px;
  color: var(--text-3);
  padding: 6px 8px;
}

.bp-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: 10px 12px;
  box-shadow: var(--sh-1);
  transition: box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.bp-card:hover {
  box-shadow: var(--sh-2);
  border-color: var(--line-strong);
}
.bp-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.bp-card-name {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.005em;
}
.bp-card-meta { font-size: 11px; color: var(--text-3); }
.mono { font-family: var(--font-mono, 'JetBrains Mono', 'SF Mono', Menlo, monospace); }

.bp-fields { display: flex; flex-direction: column; gap: 4px; }
.bp-field {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  border-radius: var(--r-1, 4px);
  font-size: 11.5px;
  color: var(--text-2);
}
.bp-field.is-new {
  background: var(--brand-soft);
  color: var(--brand-text);
}
.bp-field-name { flex: 1; color: var(--text); font-weight: var(--fw-medium, 500); }
.bp-field-code { color: var(--text-3); font-size: 11px; }
.bp-field-type { color: var(--brand-text); font-size: 11px; }

.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  padding: 0 6px;
  border-radius: var(--r-1, 4px);
  font-size: 10.5px;
  font-weight: var(--fw-medium, 500);
  background: var(--surface-3);
  color: var(--text-2);
  border: 1px solid transparent;
}
.badge-amber { background: var(--warn-soft); color: var(--warn); }
.badge-brand { background: var(--brand-soft); color: var(--brand-text); }
.badge-outline {
  background: transparent;
  border-color: var(--line-strong);
  color: var(--text-2);
}

.bp-flow-chain { font-size: 11.5px; color: var(--text-2); line-height: 1.6; }
.bp-form-section { margin-top: 6px; }
.bp-form-section-title {
  font-size: 11.5px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}
.bp-form-fields { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.bp-dict { font-size: 11px; color: var(--text-2); line-height: 1.6; }

/* Dark theme — v3 tokens cascade automatically; just nudge a couple of items
   where the alias map doesn't fit the contextual surface. */
html[data-theme="dark"] .bp-card {
  background: var(--surface-2);
}
html[data-theme="dark"] .bp-section-head:hover {
  background: var(--brand-soft);
  color: var(--brand);
}
</style>

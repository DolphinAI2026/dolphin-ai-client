<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

// New canonical key. Old key 'aPaaS:seenOnboarding' was inconsistent across
// browsers (some users reported tour re-popping every refresh). Migrating to
// a plain ASCII key + defensive try/catch (incognito / Safari ITP / quota
// errors silently broke setItem in some environments).
const STORAGE_KEY = 'apaas-onboarding-dismissed-v2'
const LEGACY_STORAGE_KEY = 'aPaaS:seenOnboarding'

function isDismissed(): boolean {
  try {
    if (localStorage.getItem(STORAGE_KEY) === '1') return true
    // Migrate legacy users who already dismissed once
    if (localStorage.getItem(LEGACY_STORAGE_KEY) === '1') {
      try { localStorage.setItem(STORAGE_KEY, '1') } catch { /* ignore */ }
      return true
    }
    return false
  } catch {
    // localStorage unavailable (private mode etc.) — treat as dismissed so
    // we don't pop the overlay every refresh.
    return true
  }
}

function markDismissed() {
  try {
    localStorage.setItem(STORAGE_KEY, '1')
    localStorage.setItem(LEGACY_STORAGE_KEY, '1')
  } catch { /* ignore */ }
}

// Default closed. Only open if NOT dismissed — checked synchronously in
// onMounted so async data fetch can never accidentally flip it open.
const visible = ref(false)
const step = ref(0) // 0, 1, 2

const counts = ref({ apps: 0, specs: 0, industry: 0, marketplace: 0 })

const FLOW_STEPS = [
  { n: '01', label: '描述需求',     tone: 'ai',     desc: '在首页输入业务需求或上传 .md 设计文档' },
  { n: '02', label: '生成 SPEC',    tone: 'brand',  desc: '睿鲸 AI Builder 边对话边产出结构化设计文档' },
  { n: '03', label: '复用行业沉淀', tone: 'emerald',desc: '从行业知识库一键复用已沉淀的模型、流程、字典' },
  { n: '04', label: '部署上线',     tone: 'amber',  desc: '一键部署到得帆云 dev / test / prod 环境' },
]

const CONCEPTS = computed(() => [
  { name: '应用',         desc: '一个完整的 aPaaS 应用，含模型 / 表单 / 流程 / 权限',  icon: 'apps',     count: counts.value.apps > 0 ? `${counts.value.apps} 个` : '—' },
  { name: 'SPEC',         desc: '设计文档，AI Builder 对话产生的中间产物，可版本管理', icon: 'doc',      count: counts.value.specs > 0 ? `${counts.value.specs} 版本` : '—' },
  { name: '行业知识库',   desc: '行业最佳实践沉淀的可复用「行业包」，含业务对象图谱',  icon: 'industry', count: counts.value.industry > 0 ? `${counts.value.industry} 包` : '—' },
  { name: '组件市场',     desc: '睿鲸 AI Coding 产出的低代码组件 / 页面 / 接口',       icon: 'store',    count: counts.value.marketplace > 0 ? `${counts.value.marketplace} 个` : '—' },
])

const ROLES = [
  { id: 'business', name: '业务顾问',     tone: 'ai',      desc: '描述需求 → SPEC → 部署',         positions: '实施顾问 / 产品经理',         path: '睿鲸 AI Builder',     recommended: false },
  { id: 'developer', name: '开发人员',    tone: 'brand',   desc: '业务搭建 ↔ 自研组件',           positions: '前端 / 全栈工程师',           path: '睿鲸 AI Coding · Vibe Coding', recommended: false },
  { id: 'hybrid',   name: '双栖',         tone: 'brand-strong', desc: '业务+开发 全链路',         positions: '产品技术负责人 / 资深实施',   path: '全部',                  recommended: true },
  { id: 'admin',    name: '平台管理员',   tone: 'rose',    desc: '运行与发布 + 平台管理',         positions: '运维 / IT 负责人',           path: '运行与发布 · 平台管理', recommended: false },
]

onMounted(async () => {
  // Open if never seen — check synchronously BEFORE any await so the
  // visibility decision can't be affected by the async data fetch below.
  if (!isDismissed()) {
    visible.value = true
  }
  // Fetch real counts for concept cards (silent fail — counts stay 0 / "—")
  try {
    const [apps, specs, industry] = await Promise.all([
      (await import('@/api/application')).applicationApi.list?.({ include_remote: false } as any).catch(() => []),
      (await import('@/api/specsV2')).specsV2Api.list().catch(() => ({ specs: [], total: 0 })),
      (await import('@/api/industry')).industryApi.listPacks().catch(() => ({ packs: [] })),
    ])
    counts.value.apps = Array.isArray(apps) ? apps.length : ((apps as any)?.items?.length || (apps as any)?.total || 0)
    counts.value.specs = (specs as any)?.total || (specs as any)?.specs?.length || 0
    counts.value.industry = ((industry as any)?.packs || []).length
    counts.value.marketplace = 0  // no marketplace count API yet
  } catch {
    // silent fail — counts stay 0
  }
})

function close() {
  // Persist BEFORE hiding so a refresh mid-animation still counts as dismissed.
  markDismissed()
  visible.value = false
}
function next() {
  if (step.value < 2) step.value++
  else close()
}
function back() {
  if (step.value > 0) step.value--
}

// Expose `open()` so a future "重新介绍" button can force-show without
// clearing the flag. Does NOT auto-mark dismissed — user must click 跳过/完成.
defineExpose({ open: () => { step.value = 0; visible.value = true } })
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="onb-overlay" data-design="v2">
      <div class="onb-panel">
        <header class="onb-head">
          <div class="onb-step-dots">
            <span v-for="i in 3" :key="i" class="onb-dot" :class="{ active: step + 1 === i }" />
          </div>
          <button class="onb-skip" @click="close">跳过</button>
        </header>

        <!-- Step 0: welcome -->
        <section v-if="step === 0" class="onb-body">
          <h2 class="onb-title">欢迎使用 aPaaS Builder</h2>
          <p class="onb-subtitle">从想法到上线，全过程在这里完成 — 业务顾问 + AI + 开发的协作平台。</p>
          <div class="onb-flow">
            <div v-for="(s, i) in FLOW_STEPS" :key="s.n" class="onb-flow-step" :class="['tone-' + s.tone, { active: i === 0 }]">
              <div class="onb-flow-num">{{ s.n }}</div>
              <div class="onb-flow-label">{{ s.label }}</div>
              <div class="onb-flow-desc">{{ s.desc }}</div>
            </div>
          </div>
        </section>

        <!-- Step 1: concepts -->
        <section v-if="step === 1" class="onb-body">
          <h2 class="onb-title">关键概念</h2>
          <p class="onb-subtitle">4 个核心概念，构成 aPaaS Builder 的工作单元。</p>
          <div class="onb-concept-grid">
            <div v-for="c in CONCEPTS" :key="c.name" class="onb-concept-card">
              <div class="onb-concept-name">{{ c.name }}</div>
              <div class="onb-concept-count">{{ c.count }}</div>
              <div class="onb-concept-desc">{{ c.desc }}</div>
            </div>
          </div>
        </section>

        <!-- Step 2: pick role -->
        <section v-if="step === 2" class="onb-body">
          <h2 class="onb-title">选个起点</h2>
          <p class="onb-subtitle">不同角色推荐不同入口。<b>视图随时可切 — 所有人都能访问相同数据。</b></p>
          <div class="onb-tip">「双栖」是我们最推荐的 — 既能聊需求也能动代码，能力上限最高。</div>
          <div class="onb-role-grid">
            <div v-for="r in ROLES" :key="r.id" class="onb-role-card" :class="['tone-' + r.tone, { recommended: r.recommended }]">
              <div class="onb-role-head">
                <span class="onb-role-name">{{ r.name }}</span>
                <span v-if="r.recommended" class="onb-role-badge">推荐</span>
              </div>
              <div class="onb-role-desc">{{ r.desc }}</div>
              <div class="onb-role-positions">{{ r.positions }}</div>
              <div class="onb-role-path">推荐入口：{{ r.path }}</div>
            </div>
          </div>
        </section>

        <footer class="onb-foot">
          <button v-if="step > 0" class="onb-btn-secondary" @click="back">上一步</button>
          <div style="flex:1" />
          <button class="onb-btn-primary" @click="next">{{ step === 2 ? '开始使用' : '下一步' }}</button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.onb-overlay {
  position: fixed; inset: 0; z-index: 9000;
  background: rgba(11, 10, 20, 0.42);
  backdrop-filter: blur(4px);
  display: grid; place-items: center;
  padding: 24px;
}
.onb-panel {
  width: 720px; max-width: 100%;
  background: var(--glass-strong, var(--surface));
  backdrop-filter: blur(20px);
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  box-shadow: var(--shadow-xl);
  overflow: hidden;
  display: flex; flex-direction: column;
  max-height: 80vh;
}
.onb-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--border);
}
.onb-step-dots { display: flex; gap: 6px; }
.onb-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--surface-3); transition: background 0.2s; }
.onb-dot.active { background: var(--brand); width: 18px; border-radius: 999px; }
.onb-skip { background: none; border: none; cursor: pointer; font-family: inherit; font-size: 12.5px; color: var(--text-3); padding: 4px 8px; border-radius: 6px; }
.onb-skip:hover { background: var(--surface-2); color: var(--text-2); }
.onb-body { padding: 28px 32px; overflow-y: auto; }
.onb-title { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; color: var(--text); margin: 0 0 8px; }
.onb-subtitle { font-size: 13.5px; color: var(--text-2); margin: 0 0 24px; line-height: 1.55; }
.onb-subtitle b { color: var(--text); font-weight: 600; }
.onb-tip { padding: 10px 14px; background: var(--ai-soft); color: var(--ai-text); border-radius: 8px; font-size: 12.5px; margin-bottom: 16px; }
.onb-flow { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.onb-flow-step { padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.onb-flow-step.tone-ai     { border-color: var(--ai-soft-2); background: var(--ai-soft); }
.onb-flow-step.tone-brand  { border-color: var(--brand-200); background: var(--brand-soft); }
.onb-flow-step.tone-emerald{ border-color: var(--emerald); background: var(--emerald-bg); }
.onb-flow-step.tone-amber  { border-color: var(--amber); background: var(--amber-bg); }
.onb-flow-step.active { box-shadow: 0 0 0 3px var(--brand-ring); }
.onb-flow-num { font-family: var(--d-font-mono); font-size: 11px; font-weight: 700; color: var(--text-3); }
.onb-flow-label { font-size: 14px; font-weight: 600; color: var(--text); margin-top: 4px; }
.onb-flow-desc { font-size: 11.5px; color: var(--text-2); margin-top: 6px; line-height: 1.55; }
.onb-concept-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.onb-concept-card { padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.onb-concept-name { font-size: 14px; font-weight: 600; color: var(--text); }
.onb-concept-count { font-size: 11px; color: var(--brand-text); font-family: var(--d-font-mono); margin-top: 2px; }
.onb-concept-desc { font-size: 12px; color: var(--text-2); margin-top: 8px; line-height: 1.55; }
.onb-role-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.onb-role-card { padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
.onb-role-card.recommended { border-color: var(--brand); background: var(--brand-soft); box-shadow: 0 0 0 3px var(--brand-ring); }
.onb-role-head { display: flex; align-items: center; justify-content: space-between; }
.onb-role-name { font-size: 13.5px; font-weight: 600; color: var(--text); }
.onb-role-badge { font-size: 10px; font-weight: 700; padding: 2px 7px; background: var(--brand); color: #fff; border-radius: 999px; }
.onb-role-desc { font-size: 11.5px; color: var(--text-2); margin-top: 4px; }
.onb-role-positions { font-size: 11px; color: var(--text-3); margin-top: 6px; }
.onb-role-path { font-size: 11.5px; color: var(--brand-text); margin-top: 4px; font-weight: 500; }
.onb-foot { display: flex; align-items: center; gap: 8px; padding: 14px 18px; border-top: 1px solid var(--border); background: var(--surface-2); }
.onb-btn-primary { height: 36px; padding: 0 18px; border-radius: 8px; background: var(--brand); color: #fff; border: none; font-size: 13.5px; font-weight: 500; cursor: pointer; font-family: inherit; }
.onb-btn-primary:hover { background: var(--brand-hover); }
.onb-btn-secondary { height: 36px; padding: 0 14px; border-radius: 8px; background: var(--surface); color: var(--text); border: 1px solid var(--border-strong); font-size: 13.5px; font-weight: 500; cursor: pointer; font-family: inherit; }
.onb-btn-secondary:hover { background: var(--surface-2); }
</style>

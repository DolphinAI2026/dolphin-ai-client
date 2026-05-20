<!-- frontend/src/views/Landing.vue
  v2 Landing — cyan AI hub + 3-mode composer + 4-stat strip + flow chips + recent apps.
  Composer 自己处理多文件 / 应用选择 / 路由 — Landing 只负责 fetch + 传 props。
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import LandingComposer from '@/components/v2/LandingComposer.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import { applicationApi } from '@/api/application'
import { industryApi } from '@/api/industry'

const router = useRouter()

interface RecentApp {
  id: number | string
  name: string
  updatedAt: string
  conversationId?: number | null
}

interface ComposerApp { id: number | string; name: string; code?: string }

const stats = ref({ apps: 0, specs: 0, deploys: 0, packs: 0 })
const recent = ref<RecentApp[]>([])
const allApps = ref<ComposerApp[]>([])

const FLOW_STEPS = [
  { n: '01', label: '描述需求',         tone: 'ai' },
  { n: '02', label: '生成 SPEC',        tone: 'brand' },
  { n: '03', label: '复用行业沉淀',     tone: 'emerald' },
  { n: '04', label: '部署上线',         tone: 'amber' },
]

function formatDate(dateStr: string) {
  if (!dateStr) return '今天'
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

function buildFallbackAppsFromConversations(list: ConversationWithApp[]) {
  const appMap = new Map<number, ConversationWithApp>()
  for (const conv of list) {
    if (!conv.app_id || !conv.app_name) continue
    const existing = appMap.get(conv.app_id)
    const convTime = new Date(conv.updated_at || conv.created_at || 0).getTime()
    const existingTime = existing ? new Date(existing.updated_at || existing.created_at || 0).getTime() : -1
    if (!existing || convTime > existingTime) appMap.set(conv.app_id, conv)
  }
  return Array.from(appMap.values()).sort((a, b) => {
    const ta = new Date(a.updated_at || a.created_at || 0).getTime()
    const tb = new Date(b.updated_at || b.created_at || 0).getTime()
    return tb - ta
  })
}

async function loadLanding() {
  const [conversations, apps, industryPacks] = await Promise.all([
    conversationApi.listWithApps({ agent_type: 'builder' }).catch(() => [] as ConversationWithApp[]),
    applicationApi.list({ include_remote: true }).catch(() => [] as any[]),
    industryApi.listPacks().catch(() => ({ packs: [] as any[] })),
  ])

  const appRecords = Array.isArray(apps)
    ? apps
        .filter((app: any) => app?.id && app?.app_name)
        .sort((a: any, b: any) => {
          const ta = new Date(a.updated_at || a.created_at || 0).getTime()
          const tb = new Date(b.updated_at || b.created_at || 0).getTime()
          return tb - ta
        })
        .map((app: any) => ({
          id: app.id,
          name: app.app_name || app.appName || '未命名应用',
          updatedAt: formatDate(app.updated_at || app.created_at || ''),
          conversationId: app.conversation_id ?? null,
        } as RecentApp))
    : []

  const fallbackApps = buildFallbackAppsFromConversations(conversations).map(conv => ({
    id: conv.app_id as number,
    name: conv.app_name || '未命名应用',
    updatedAt: formatDate(conv.updated_at || conv.created_at || ''),
    conversationId: conv.id,
  } as RecentApp))

  const sourceApps = appRecords.length ? appRecords : fallbackApps
  recent.value = sourceApps.slice(0, 5)

  // 应用选择器用：全量 apps（带 code），优先用 backend appRecords，fallback 用 conversations 推断的
  allApps.value = Array.isArray(apps)
    ? apps
        .filter((app: any) => app?.id && app?.app_name)
        .map((app: any) => ({
          id: app.id,
          name: app.app_name || app.appName || '未命名应用',
          code: app.app_code || app.appCode || undefined,
        } as ComposerApp))
    : []

  // 4-stat strip: apps / specs / deploys / packs.
  // - apps: total app count
  // - specs: total conversation count (each builder conversation produces SPEC iterations)
  // - deploys: sum of deploy counts across apps (apaas_app_id != null implies deployed)
  // - packs: industry packs from /industry/packs (defaults 0 if API down)
  const deployedCount = Array.isArray(apps)
    ? apps.filter((app: any) => app?.apaas_app_id).length
    : 0
  const packsCount = ((industryPacks as any)?.packs || []).length
  stats.value = {
    apps: sourceApps.length,
    specs: conversations.length,
    deploys: deployedCount,
    packs: packsCount,
  }
}

function openApp(r: RecentApp) {
  // 与旧 Landing.vue 一致：带 app_id 进入 ChatPage（router guard 已放行 app_id）
  router.push({ path: '/chat', query: { app_id: String(r.id) } })
}

const recentCount = computed(() => recent.value.length)

onMounted(loadLanding)
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="page landing">
      <div class="page-pad">
        <div class="hero">
          <div class="ai-badge">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/><path d="M19 17l1 3 3 1-3 1-1 3-1-3-3-1 3-1z"/></svg>
            <span>AI</span>
          </div>
          <div class="eyebrow">APAAS CHAT AI · DESIGN + BUILD</div>
          <h1 class="hero-title">把<span class="hl">想法或材料</span>给 AI，<br/>它来搭<span class="hl">应用</span>。</h1>
          <div class="hero-sub">支持 .md 设计文档 · .doc / .docx · .pdf · 直接对话需求 · 复用行业包 · 部署到得帆云</div>
        </div>

        <LandingComposer :apps="allApps" />

        <div class="strip stats">
          <div class="stat"><div class="stat-num">{{ stats.apps }}</div><div class="stat-lbl">应用</div></div>
          <div class="stat"><div class="stat-num">{{ stats.specs }}</div><div class="stat-lbl">SPEC 版本</div></div>
          <div class="stat"><div class="stat-num">{{ stats.deploys }}</div><div class="stat-lbl">部署次数</div></div>
          <div class="stat"><div class="stat-num">{{ stats.packs }}</div><div class="stat-lbl">行业包</div></div>
        </div>

        <div class="flow">
          <div v-for="(s, i) in FLOW_STEPS" :key="s.n" class="flow-step" :class="'tone-' + s.tone">
            <div class="flow-num">{{ s.n }}</div>
            <div class="flow-label">{{ s.label }}</div>
            <svg v-if="i < FLOW_STEPS.length - 1" class="flow-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m13 5 7 7-7 7"/></svg>
          </div>
        </div>

        <div class="section-head">
          <div class="section-title">最近应用 <span class="section-title-count">{{ recentCount }}</span></div>
          <button class="section-action" @click="router.push('/apps')">查看全部 →</button>
        </div>
        <div class="recent" v-if="recent.length">
          <button v-for="r in recent" :key="r.id" class="recent-row" @click="openApp(r)">
            <div class="recent-name">{{ r.name }}</div>
            <div class="recent-when">{{ r.updatedAt }}</div>
          </button>
        </div>
        <div v-else class="recent-empty">还没有应用 — 上面输入框开始描述需求，或者 <a @click.prevent="router.push('/apps')">浏览应用</a>。</div>
      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
.landing { overflow-y: auto; height: 100%; background: var(--bg-app); flex: 1; min-height: 0; }
.page-pad { padding: 48px 32px 80px; max-width: 960px; margin: 0 auto; }
.hero { text-align: center; margin-bottom: 36px; }
.ai-badge { display: inline-flex; align-items: center; gap: 6px; height: 38px; padding: 0 14px; border-radius: 999px; background: var(--ai-soft); color: var(--ai-text); font-weight: 700; font-size: 14px; letter-spacing: 0.02em; border: 1px solid var(--ai-soft-2); margin-bottom: 14px; }
.eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 0.20em; text-transform: uppercase; color: var(--ai-text); margin-bottom: 16px; }
.hero-title { font-size: 38px; font-weight: 700; color: var(--text); letter-spacing: -0.025em; line-height: 1.15; margin: 0 0 14px; }
.hero-title .hl { color: var(--ai-text); }
.hero-sub { font-size: 13.5px; color: var(--text-2); max-width: 600px; margin: 0 auto; line-height: 1.6; }
.strip.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 32px 0 22px; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; text-align: center; box-shadow: var(--shadow-xs); }
.stat-num { font-size: 26px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1; }
.stat-lbl { font-size: 12px; color: var(--text-3); margin-top: 4px; }
.flow { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 28px; }
.flow-step { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px; background: var(--surface); border: 1px solid var(--border); }
.flow-step.tone-ai      { color: var(--ai-text);     background: var(--ai-soft); }
.flow-step.tone-brand   { color: var(--brand-text);  background: var(--brand-soft); }
.flow-step.tone-emerald { color: var(--emerald);     background: var(--emerald-bg); }
.flow-step.tone-amber   { color: var(--amber);       background: var(--amber-bg); }
.flow-num { font-family: var(--d-font-mono); font-size: 11px; font-weight: 700; }
.flow-label { font-size: 12.5px; font-weight: 500; }
.flow-arrow { color: var(--text-4); margin: 0 -2px; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 24px 0 12px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 8px; }
.section-title-count { font-size: 12px; color: var(--text-3); font-weight: 500; }
.section-action { font-size: 12.5px; color: var(--brand-text); font-weight: 500; background: none; border: none; cursor: pointer; padding: 4px 8px; border-radius: 6px; font-family: inherit; }
.section-action:hover { background: var(--brand-soft); }
.recent { display: flex; flex-direction: column; gap: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 6px; }
.recent-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border-radius: 8px; cursor: pointer; background: transparent; border: none; color: var(--text); font-family: inherit; }
.recent-row:hover { background: var(--surface-2); }
.recent-name { font-size: 13px; font-weight: 500; }
.recent-when { font-size: 11px; color: var(--text-3); }
.recent-empty { background: var(--surface); border: 1px dashed var(--border-strong); border-radius: 12px; padding: 24px; text-align: center; color: var(--text-3); font-size: 13px; }
.recent-empty a { color: var(--brand-text); cursor: pointer; }
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import LandingComposer from '@/components/v2/LandingComposer.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import { applicationApi } from '@/api/application'

const router = useRouter()

interface RecentApp {
  id: number | string
  name: string
  updatedAt: string
  conversationId?: number | null
}

const recent = ref<RecentApp[]>([])

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
  const [conversations, apps] = await Promise.all([
    conversationApi.listWithApps({ agent_type: 'builder' }).catch(() => [] as ConversationWithApp[]),
    applicationApi.list({ include_remote: true }).catch(() => [] as any[]),
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
}

function openApp(r: RecentApp) {
  // 与旧 Landing.vue 一致：带 app_id 进入 ChatPage（router guard 已放行 app_id）
  router.push({ path: '/chat', query: { app_id: String(r.id) } })
}

const recentCount = computed(() => recent.value.length)

onMounted(() => {
  loadLanding()
})
</script>

<template>
  <WorkbenchShell>
    <div class="page landing">
      <div class="page-pad">
        <div class="hero">
          <div class="ai-badge">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/><path d="M19 17l1 3 3 1-3 1-1 3-1-3-3-1 3-1z"/></svg>
            <span>AI</span>
          </div>
          <div class="eyebrow">DOLPHIN CODE · APAAS DELIVERY</div>
          <h1 class="hero-title">把<span class="hl">业务流程</span>说清楚，<br/>Dolphin Code 直接搭<span class="hl">应用</span>。</h1>
          <div class="hero-sub">面向 QMS、设备台账、审批流和现场管理场景，上传材料或描述需求后，AI 会整理字段、角色、流程并进入得帆云应用配置。</div>
        </div>

        <LandingComposer />

        <section class="recent-panel" aria-labelledby="recent-title">
          <div class="section-head">
            <div id="recent-title" class="section-title">最近应用 <span class="section-title-count">{{ recentCount }}</span></div>
            <button class="section-action" @click="router.push('/apps')">查看全部</button>
          </div>
          <div class="recent" v-if="recent.length">
            <button v-for="r in recent" :key="r.id" class="recent-row" @click="openApp(r)">
              <div class="recent-name">{{ r.name }}</div>
              <div class="recent-when">{{ r.updatedAt }}</div>
            </button>
          </div>
          <div v-else class="recent-empty">还没有应用，可以先从上方输入框开始。</div>
        </section>
      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
.landing { overflow-y: auto; height: 100%; background: var(--bg-app); flex: 1; min-height: 0; }
.page-pad {
  width: min(100%, 1080px);
  margin: 0 auto;
  padding: 86px 32px 72px;
}
.hero {
  text-align: center;
  margin-bottom: 34px;
}
.ai-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 42px;
  padding: 0 16px;
  border-radius: 999px;
  background: var(--ai-soft);
  color: var(--ai-text);
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0.02em;
  border: 1px solid var(--ai-soft-2);
  margin-bottom: 16px;
  font-family: var(--font-sans);
}
.eyebrow {
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--ai-text);
  margin-bottom: 14px;
  font-family: var(--font-sans);
}
.hero-title {
  font-family: var(--font-sans);
  font-size: 42px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: 0;
  line-height: 1.12;
  margin: 0 0 14px;
}
.hero-title .hl {
  font-family: inherit;
  font-weight: 700;
  color: var(--brand);
}
.hero-sub {
  font-size: 15px;
  color: var(--text-2);
  max-width: 760px;
  margin: 0 auto;
  line-height: 1.65;
  font-family: var(--font-sans);
}

.recent-panel {
  width: min(100%, 920px);
  margin: 34px auto 0;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.section-title {
  font-size: 14px;
  font-weight: 650;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-title-count { font-size: 12px; color: var(--text-3); font-weight: 500; }
.section-action { font-size: 12.5px; color: var(--brand-text); font-weight: 600; background: none; border: none; cursor: pointer; padding: 6px 8px; border-radius: 6px; font-family: inherit; }
.section-action:hover { background: var(--brand-soft); }
.recent { display: flex; flex-direction: column; gap: 6px; }
.recent-row { display: flex; align-items: center; justify-content: space-between; min-height: 54px; padding: 0 18px; border-radius: 10px; cursor: pointer; background: var(--surface); border: 1px solid var(--line, var(--border)); color: var(--text); font-family: inherit; box-shadow: var(--shadow-xs); }
.recent-row:hover { background: var(--surface-2); }
.recent-name { font-size: 14px; font-weight: 600; }
.recent-when { font-size: 12px; color: var(--text-3); }
.recent-empty { background: var(--surface); border: 1px dashed var(--line-strong, var(--border-strong)); border-radius: 12px; padding: 24px; text-align: center; color: var(--text-3); font-size: 13px; }
.recent-empty a { color: var(--brand-text); cursor: pointer; }

@media (max-width: 720px) {
  .page-pad {
    padding: 54px 18px 52px;
  }

  .hero {
    margin-bottom: 24px;
  }

  .hero-title {
    font-size: 32px;
  }

  .hero-sub {
    font-size: 14px;
  }

  .recent-panel {
    margin-top: 26px;
  }
}
</style>

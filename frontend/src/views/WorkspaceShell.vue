<template>
  <div class="workspace-shell">
    <WorkspaceTopBar
      v-if="store.application"
      :app="store.application"
      :members="store.state?.members || []"
      :git="store.state?.git ?? null"
      :effective-mode="store.effectiveMode"
      :can-toggle-mode="canToggleMode"
      @toggle-mode="onToggleMode"
    />
    <div v-if="store.loading" class="loading">加载中…</div>
    <div v-else-if="store.error" class="error">{{ store.error }}</div>
    <main v-else-if="store.state" class="ws-main">
      <section class="pane chat-pane">
        <ChatPanel />
      </section>
      <section class="pane preview-pane">
        <PreviewPanel
          :draft-spec-id="store.state.current_draft?.id ?? null"
          :canonical-spec-id="store.state.canonical?.id ?? null"
          :platform-url="store.state.application.platform_url"
          :apaas-app-id="store.state.application.apaas_app_id"
        />
      </section>
      <section class="pane activity-pane">
        <ActivityPanel
          :application-id="store.state.application.id"
          :draft="store.state.current_draft"
          :canonical="store.state.canonical"
          :proposals="store.state.open_proposals"
          :applied-history="store.state.applied_history"
          :git="store.state.git"
          :mode="store.effectiveMode"
          :role="store.state.user_role_on_app"
        />
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'
import { useUserPreferenceStore } from '@/stores/userPreference'
import { preferencesApi } from '@/api/preferences'
import { roleAtLeast } from '@/types/collaboration'
import WorkspaceTopBar from '@/components/workspace/WorkspaceTopBar.vue'
import ChatPanel from '@/components/workspace/ChatPanel.vue'
import ActivityPanel from '@/components/workspace/ActivityPanel.vue'
import PreviewPanel from '@/components/workspace/PreviewPanel.vue'

const route = useRoute()
const router = useRouter()
const store = useWorkspaceStore()
const prefStore = useUserPreferenceStore()

const appId = computed(() => Number(route.params.appId))

const canToggleMode = computed(() =>
  store.state ? roleAtLeast(store.state.user_role_on_app, 'maintainer') : false
)

async function onToggleMode(newMode: 'simple' | 'pro') {
  if (!store.state || !canToggleMode.value) return
  try {
    await preferencesApi.patchAppDefaultMode(store.state.application.id, newMode)
    await store.refresh()
  } catch (e: any) {
    console.error(e)
  }
}

onMounted(async () => {
  if (!appId.value || !Number.isFinite(appId.value)) {
    router.replace('/apps')
    return
  }
  await Promise.all([prefStore.fetch(), store.load(appId.value)])
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Maps v2 tokens (--bg-panel/--fg-muted/--t-danger) to v3 (--surface/--text-3/--err). */
.workspace-shell { display: flex; flex-direction: column; height: 100vh; background: var(--bg); color: var(--text); }
.ws-main { display: grid; grid-template-columns: 320px 1fr 320px; gap: 1px; flex: 1; min-height: 0; background: var(--line); }
.pane { background: var(--surface); overflow: auto; padding: var(--s-4, 16px); }
.loading, .error { padding: var(--s-12, 48px); text-align: center; color: var(--text-3); }
.error { color: var(--err); }
.muted { color: var(--text-3); }
</style>

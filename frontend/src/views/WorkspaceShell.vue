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
        <!-- ChatPanel — Task 6 实现，先占位 -->
        <p class="muted">ChatPanel 占位（Task 6）</p>
      </section>
      <section class="pane preview-pane">
        <!-- PreviewPanel — Task 7-9 实现 -->
        <p class="muted">PreviewPanel 占位（Tasks 7-9）</p>
      </section>
      <section class="pane activity-pane">
        <!-- ActivityPanel — Task 6 后半实现 -->
        <p class="muted">ActivityPanel 占位（Task 6）</p>
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
.workspace-shell { display: flex; flex-direction: column; height: 100vh; background: var(--bg); color: var(--fg); }
.ws-main { display: grid; grid-template-columns: 320px 1fr 320px; gap: 1px; flex: 1; min-height: 0; background: var(--line); }
.pane { background: var(--bg-panel); overflow: auto; padding: 16px; }
.loading, .error { padding: 48px; text-align: center; color: var(--fg-muted); }
.error { color: var(--t-danger); }
.muted { color: var(--fg-muted); }
</style>

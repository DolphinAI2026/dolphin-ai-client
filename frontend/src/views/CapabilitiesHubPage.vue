<template>
  <WorkbenchShell>
    <div class="capabilities-hub">
      <div class="hub-tabs" role="tablist">
      <button
        v-for="t in tabs"
        :key="t.key"
        type="button"
        role="tab"
        class="hub-tab"
        :class="{ active: active === t.key }"
        :aria-selected="active === t.key"
        @click="select(t.key)"
      >{{ t.label }}</button>
    </div>
    <div class="hub-content">
      <SkillLibraryPage v-if="active === 'skills'" />
      <KnowledgeBasePage v-else-if="active === 'knowledge'" />
      <McpToolsPage v-else-if="active === 'mcp'" />
      <PlatformEnvs v-else-if="active === 'gateway'" only="llm" />
    </div>
    </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { isDesktop } from '@/utils/desktop'
import { visibleTabs, resolveActiveTab, type HubTabKey } from '@/composables/useCapabilitiesHub'
import SkillLibraryPage from './SkillLibraryPage.vue'
import KnowledgeBasePage from './KnowledgeBasePage.vue'
import McpToolsPage from './McpToolsPage.vue'
import PlatformEnvs from './PlatformEnvs.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'

const route = useRoute()
const router = useRouter()
const user = useUserStore()

const tabs = computed(() => visibleTabs({ isPlatformAdmin: user.isPlatformAdmin, isTenantAdmin: user.isTenantAdmin, isDesktop }))
const active = computed(() => resolveActiveTab(route.query.tab as string | undefined, tabs.value))

function select(key: HubTabKey) {
  if (key === active.value) return
  router.replace({ path: '/hub', query: { tab: key } })
}
</script>

<style scoped>
.capabilities-hub {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg, #f8fafc);
}
.hub-tabs {
  flex-shrink: 0;
  display: flex;
  gap: 4px;
  padding: 8px 16px 0;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.hub-tab {
  padding: 8px 16px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-2);
  border-bottom: 2px solid transparent;
}
.hub-tab.active {
  color: var(--brand);
  border-bottom-color: var(--brand);
  font-weight: 600;
}
.hub-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
/* 四个 tab 渲染的原生页(各自 BuilderFrame)是 height:100% → 填满 .hub-content, 避免双滚动。 */
.hub-content > * {
  flex: 1;
  min-height: 0;
}
</style>

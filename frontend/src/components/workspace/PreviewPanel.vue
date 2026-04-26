<template>
  <div class="preview-panel">
    <nav class="preview-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="{ active: active === tab.key, disabled: tab.disabled }"
        :disabled="tab.disabled"
        @click="active = tab.key"
      >
        {{ tab.label }}
      </button>
    </nav>
    <div class="preview-body">
      <SpecView v-if="active === 'spec'" :draft-spec-id="draftSpecId" />
      <DeployIframe
        v-else-if="active === 'deploy'"
        :platform-url="platformUrl"
        :apaas-app-id="apaasAppId"
      />
      <CodeView v-else-if="active === 'code'" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import SpecView from './preview/SpecView.vue'
import DeployIframe from './preview/DeployIframe.vue'
import CodeView from './preview/CodeView.vue'

const props = defineProps<{
  draftSpecId: string | null
  canonicalSpecId: string | null
  platformUrl: string | null
  apaasAppId: string | null
}>()

const active = ref<'spec' | 'deploy' | 'code'>('spec')

const tabs = computed(() => [
  { key: 'spec' as const, label: 'SPEC', disabled: false },
  { key: 'deploy' as const, label: 'Deploy', disabled: !props.platformUrl || !props.apaasAppId },
  { key: 'code' as const, label: 'Code', disabled: false },
])
</script>

<style scoped>
.preview-panel { height: 100%; display: flex; flex-direction: column; }
.preview-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); padding: 0 8px; }
.preview-tabs button { background: transparent; border: 0; color: var(--fg-muted); padding: 8px 16px; cursor: pointer; border-bottom: 2px solid transparent; font-size: 13px; }
.preview-tabs button:hover:not(:disabled) { color: var(--fg); }
.preview-tabs button.active { color: var(--brand); border-bottom-color: var(--brand); }
.preview-tabs button.disabled, .preview-tabs button:disabled { opacity: 0.4; cursor: not-allowed; }
.preview-body { flex: 1; overflow: auto; }
</style>

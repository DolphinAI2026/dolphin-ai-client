<template>
  <div class="bg-tasks-panel" style="padding:12px;overflow:auto">
    <div v-if="loading">加载中…</div>
    <div v-else-if="error" class="is-error">{{ error }}</div>
    <ul v-else class="run-list">
      <li v-for="r in runs" :key="r.run_id" class="run-item" @click="openTrace(r.run_id)">
        <span class="run-status" :class="'st-' + r.status">{{ r.status }}</span>
        <span class="run-type">{{ r.agent_type }}</span>
        <span class="run-tokens">{{ r.total_tokens }} tok</span>
      </li>
    </ul>
    <AgentRunTraceDrawer v-model="traceVisible" :session-id="null" :prefer-run-id="activeRunId" />
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AgentRunTraceDrawer from '@/components/common/AgentRunTraceDrawer.vue'
import { agentObservabilityApi, type AgentRunSummary } from '@/api/agentObservability'
const runs = ref<AgentRunSummary[]>([])
const loading = ref(true)
const error = ref('')
const traceVisible = ref(false)
const activeRunId = ref<string | null>(null)
async function load() {
  loading.value = true; error.value = ''
  try { runs.value = (await agentObservabilityApi.listRuns({ limit: 50 })).runs }
  catch (e: any) { error.value = e?.message || '加载失败' }
  finally { loading.value = false }
}
function openTrace(id: string) { activeRunId.value = id; traceVisible.value = true }
onMounted(load)
</script>

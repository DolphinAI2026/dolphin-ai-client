import { defineStore } from 'pinia'
import { ref } from 'vue'
import { agentsApi, type AgentConfig } from '@/api/agents'

export const useAgentsStore = defineStore('agents', () => {
  const agents = ref<AgentConfig[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAgents() {
    loading.value = true
    error.value = null
    try {
      const resp = await agentsApi.list()
      agents.value = resp.agents
    } catch (e: any) {
      error.value = e?.message || 'fetch agents failed'
    } finally {
      loading.value = false
    }
  }

  async function saveAgent(agentId: string, payload: { model?: string; system_prompt?: string }) {
    const updated = await agentsApi.update(agentId, payload)
    const idx = agents.value.findIndex(a => a.id === agentId)
    if (idx >= 0) agents.value[idx] = updated
    return updated
  }

  return {
    agents, loading, error,
    fetchAgents, saveAgent,
  }
})

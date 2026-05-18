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

  function _replaceAgent(updated: AgentConfig) {
    const idx = agents.value.findIndex(a => a.id === updated.id)
    if (idx >= 0) agents.value[idx] = updated
  }

  async function addSkillBinding(agentId: string, code: string) {
    const updated = await agentsApi.addSkill(agentId, code)
    _replaceAgent(updated)
    return updated
  }

  async function removeSkillBinding(agentId: string, code: string) {
    const updated = await agentsApi.removeSkill(agentId, code)
    _replaceAgent(updated)
    return updated
  }

  async function addMcpBinding(agentId: string, mcpId: string) {
    const updated = await agentsApi.addMcp(agentId, mcpId)
    _replaceAgent(updated)
    return updated
  }

  async function removeMcpBinding(agentId: string, mcpId: string) {
    const updated = await agentsApi.removeMcp(agentId, mcpId)
    _replaceAgent(updated)
    return updated
  }

  return {
    agents, loading, error,
    fetchAgents, saveAgent,
    addSkillBinding, removeSkillBinding,
    addMcpBinding, removeMcpBinding,
  }
})

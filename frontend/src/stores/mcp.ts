import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { mcpApi, type McpServer } from '@/api/mcp'

export const useMcpStore = defineStore('mcp', () => {
  const servers = ref<McpServer[]>([])
  const total = ref(0)
  const connectedCount = ref(0)
  const errorCount = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const toolsTotal = computed(() => servers.value.reduce((a, s) => a + s.tools, 0))

  async function fetchServers() {
    loading.value = true
    error.value = null
    try {
      const r = await mcpApi.listServers()
      servers.value = r.servers
      total.value = r.total
      connectedCount.value = r.connected
      errorCount.value = r.errors
    } catch (e: any) {
      error.value = e?.message || 'fetch mcp servers failed'
    } finally {
      loading.value = false
    }
  }

  return { servers, total, connectedCount, errorCount, toolsTotal, loading, error, fetchServers }
})

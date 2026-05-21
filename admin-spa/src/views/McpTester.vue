<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>MCP 测试台</h1>
        <p>获取工具列表只校验 MCP 凭证；调用具体工具时再填写 aPaaS 用户凭证、租户 ID 和工具参数。</p>
      </div>
    </div>

    <el-card class="section">
      <template #header>一、获取工具列表</template>
      <el-form label-width="120px">
        <el-form-item label="MCP 服务">
          <el-select v-model="form.serviceCode" style="width: 100%" @change="onServiceChange">
            <el-option
              v-for="item in services"
              :key="item.code"
              :label="`${item.name}（${item.tools} 个工具）`"
              :value="item.code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="服务 URL">
          <el-input v-model="form.url" disabled />
        </el-form-item>
        <el-form-item label="MCP 凭证">
          <el-input v-model="form.key" type="password" show-password />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="loadingTools" @click="loadTools">测试连接并获取工具</el-button>
      <el-alert
        v-if="toolsMessage"
        :title="toolsMessage"
        :type="tools.length ? 'success' : 'warning'"
        show-icon
        :closable="false"
        style="margin-top: 12px"
      />
    </el-card>

    <el-card class="section">
      <template #header>工具列表（{{ tools.length }}）</template>
      <el-table :data="tools" height="360" stripe>
        <el-table-column label="工具名" prop="name" min-width="220" />
        <el-table-column label="说明" prop="description" min-width="420" show-overflow-tooltip />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="selectTool(row)">测试</el-button>
          </template>
        </el-table-column>
        <!-- v3 2026-05-20 UED 报告 P3: "No Data" 英文残留 → 中文引导 + 指示下一步 -->
        <template #empty>
          <div style="padding: 24px 16px; color: var(--text-3); font-size: 13px; line-height: 1.6">
            暂无工具数据，请先在上方填写 MCP 服务地址并点击「连接服务」获取工具列表。
          </div>
        </template>
      </el-table>
    </el-card>

    <el-card class="section">
      <template #header>二、调用工具</template>
      <el-form label-width="130px">
        <el-form-item label="当前工具">
          <el-select v-model="callForm.toolName" filterable placeholder="请选择要测试的工具" style="width: 100%" @change="onToolChange">
            <el-option
              v-for="item in tools"
              :key="item.name"
              :label="item.name"
              :value="item.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="租户管理员">
          <div class="inline-row">
            <el-select
              v-model="selectedTenantUserKey"
              filterable
              placeholder="选择租户管理员用户"
              style="width: 460px"
              @change="onTenantUserChange"
            >
              <el-option
                v-for="item in tenantUsers"
                :key="item.key"
                :label="`${item.tenantName} / ${item.username || item.account}（${item.account}）`"
                :value="item.key"
              />
            </el-select>
            <el-input v-model="tenantPassword" type="password" show-password placeholder="租户管理员密码" style="width: 260px" />
            <el-button :loading="tokenLoading" :disabled="!selectedTenantUserKey" @click="fetchTenantUserToken">获取 Token</el-button>
          </div>
        </el-form-item>
        <el-form-item label="aPaaS 用户凭证">
          <el-input v-model="callForm.apaasToken" placeholder="调用具体工具时必填" type="password" show-password />
        </el-form-item>
        <el-form-item label="租户 ID">
          <el-input v-model="callForm.tenantId" placeholder="调用具体工具时必填" />
        </el-form-item>
        <el-form-item label="工具参数 JSON">
          <el-input
            v-model="callForm.argsJson"
            type="textarea"
            :rows="8"
            :placeholder="argsPlaceholder"
          />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="calling" :disabled="!callForm.toolName" @click="callTool">
        调用工具
      </el-button>
    </el-card>

    <el-card v-if="resultText" class="section">
      <template #header>原始响应</template>
      <pre class="result">{{ resultText }}</pre>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { API_BASE_URL, apiGet, apiPost } from '@/api/client'

interface ToolItem {
  name: string
  description?: string
  inputSchema?: any
}

interface AdminRow {
  id: string
  name: string
  account: string
  is_default: boolean
}

interface TenantUserRow {
  key: string
  id: string
  account: string
  username: string
  tenantId: string
  tenantName: string
  tenantCode: string
}

const route = useRoute()

const services = [
  { name: '主工具服务', code: 'apaas-builder-mcp', url: resolveMcpUrl('/api/mcp/mcp'), tools: 33 },
  { name: 'Builder 场景服务', code: 'apaas-builder-config', url: resolveMcpUrl('/api/mcp-builder/mcp'), tools: 14 },
  { name: 'Coding 工作区服务', code: 'apaas-builder-coding', url: resolveMcpUrl('/api/mcp-coding/mcp'), tools: 23 },
  { name: 'Vibe 开发服务', code: 'apaas-builder-vibe', url: resolveMcpUrl('/api/mcp-vibe/mcp'), tools: 9 },
  { name: '设计解析服务', code: 'apaas-builder-design', url: resolveMcpUrl('/api/mcp-design/mcp'), tools: 4 },
]

const form = reactive({
  serviceCode: 'apaas-builder-mcp',
  url: resolveMcpUrl('/api/mcp/mcp'),
  key: '',
})

const callForm = reactive({
  toolName: '',
  apaasToken: '',
  tenantId: '',
  argsJson: '{}',
})

const tools = ref<ToolItem[]>([])
const admins = ref<AdminRow[]>([])
const tenantUsers = ref<TenantUserRow[]>([])
const selectedTenantUserKey = ref('')
const tenantPassword = ref('')
const toolsMessage = ref('')
const resultText = ref('')
const loadingTools = ref(false)
const calling = ref(false)
const tokenLoading = ref(false)
// v3 2026-05-21 UED 报告 P1: 切服务时回滚用 — 记住上一次成功的 serviceCode
const lastServiceCode = ref('apaas-builder-mcp')
const selectedTool = computed(() => tools.value.find((item) => item.name === callForm.toolName))
const ENV_PARAM_KEYS = new Set(['env', 'env_id', 'alias', 'platform_env_id'])
const argsPlaceholder = computed(() => {
  if (!selectedTool.value?.inputSchema) return '例如：{}'
  return JSON.stringify(buildExampleFromSchema(selectedTool.value.inputSchema), null, 2)
})

function headers(includeApaas = false) {
  const rawKey = form.key.trim().replace(/^Bearer\s+/i, '')
  const h: Record<string, string> = {
    Accept: 'application/json, text/event-stream',
    'Content-Type': 'application/json',
    Authorization: `Bearer ${rawKey}`,
  }
  if (includeApaas) {
    h['X-APaaS-Token'] = callForm.apaasToken.trim()
    h['X-APaaS-Tenant-Id'] = callForm.tenantId.trim()
  }
  return h
}

function resolveMcpUrl(url: string) {
  const apiBase = API_BASE_URL.replace(/\/+$/, '')
  const raw = (url || '').trim()
  if (!raw) return raw
  if (/^https?:\/\//i.test(raw)) return raw
  if (raw === '/api') return apiBase
  if (raw.startsWith('/api/')) return `${apiBase}${raw.slice('/api'.length)}`
  if (raw.startsWith('api/')) return `${apiBase}/${raw.slice('api/'.length)}`
  return raw
}

async function loadTools(silent = false): Promise<boolean> {
  if (!form.url || !form.key.trim()) {
    if (!silent) ElMessage.warning('请选择 MCP 服务并填写 MCP 凭证')
    return false
  }
  loadingTools.value = true
  toolsMessage.value = silent ? '切换中…' : ''
  resultText.value = ''
  try {
    const resp = await fetch(resolveMcpUrl(form.url), {
      method: 'POST',
      headers: headers(false),
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} }),
    })
    const text = await resp.text()
    resultText.value = text
    let data: any
    try {
      data = JSON.parse(text)
    } catch {
      data = {}
    }
    const list = data?.result?.tools || data?.tools || []
    tools.value = Array.isArray(list) ? list : []
    if (tools.value.length) {
      toolsMessage.value = `获取成功，共 ${tools.value.length} 个工具`
      return true
    } else if (text.includes('missing end-user identity')) {
      toolsMessage.value = '后端当前仍要求用户身份。需要把工具清单放开为只校验 MCP 凭证。'
      return false
    } else {
      toolsMessage.value = `未获取到工具列表：HTTP ${resp.status}，${text.slice(0, 160)}`
      return false
    }
  } catch (err: any) {
    tools.value = []
    toolsMessage.value = err?.message || '获取工具列表失败'
    return false
  } finally {
    loadingTools.value = false
  }
}

function selectTool(tool: ToolItem) {
  callForm.toolName = tool.name
  callForm.argsJson = JSON.stringify(buildExampleFromSchema(tool.inputSchema), null, 2)
}

function onToolChange(name: string) {
  const tool = tools.value.find((item) => item.name === name)
  if (tool) selectTool(tool)
}

function buildExampleFromSchema(schema: any) {
  const props = schema?.properties || {}
  const result: Record<string, any> = {}
  for (const [key, def] of Object.entries<any>(props)) {
    if (ENV_PARAM_KEYS.has(key)) continue
    if (def?.default !== undefined) result[key] = def.default
    else if (def?.enum?.length) result[key] = def.enum[0]
    else if (def?.type === 'boolean') result[key] = false
    else if (def?.type === 'number' || def?.type === 'integer') result[key] = 0
    else if (def?.type === 'array') result[key] = []
    else if (def?.type === 'object') result[key] = {}
    else result[key] = ''
  }
  return result
}

async function onServiceChange(code: string) {
  const service = services.find((item) => item.code === code)
  if (!service) return
  form.url = service.url
  tools.value = []
  resultText.value = ''
  // v3 2026-05-21 UED 报告 P1: 切换服务后自动重新拉工具列表，
  // 不要让用户再手动点"测试连接并获取工具列表"。
  // 没填 MCP 凭证 / 失败时静默回滚到上一个服务，提示用户。
  if (!form.key.trim()) {
    toolsMessage.value = '请先填写 MCP 凭证'
    lastServiceCode.value = code
    return
  }
  toolsMessage.value = '切换中…'
  const ok = await loadTools(true)
  if (ok) {
    lastServiceCode.value = code
  } else {
    // 回滚到上一个成功的服务，避免用户卡在坏状态
    if (lastServiceCode.value && lastServiceCode.value !== code) {
      ElMessage.warning(`切到「${service.name || code}」失败，已回到上一个服务`)
      form.serviceCode = lastServiceCode.value
      const prev = services.find((item) => item.code === lastServiceCode.value)
      if (prev) form.url = prev.url
    } else {
      lastServiceCode.value = code
    }
  }
}

async function loadAdmins() {
  const resp = await apiGet<{ items: AdminRow[] }>('/mcp-platform/apaas-admins').catch(() => ({ items: [] }))
  admins.value = resp.items || []
}

function flattenTenantAdmins(tenants: any[]): TenantUserRow[] {
  const seen = new Set<string>()
  const result: TenantUserRow[] = []
  for (const tenant of tenants || []) {
    const adminList = Array.isArray(tenant?.adminList) ? tenant.adminList : []
    const tenantId = String(tenant?.tenantId || tenant?.tenant_id || tenant?.id || '')
    for (const item of adminList) {
      const key = `${tenantId}:${item?.id || item?.account || item?.username || ''}`
      if (seen.has(key)) continue
      seen.add(key)
      result.push({
        key,
        id: String(item?.id || ''),
        account: item?.account || '',
        username: item?.username || item?.name || '',
        tenantId,
        tenantName: tenant?.name || tenant?.tenantName || '',
        tenantCode: tenant?.tenantCode || tenant?.code || '',
      })
    }
  }
  return result
}

async function loadTenantUsers() {
  const resp = await apiGet<{ items: any[] }>('/mcp-platform/apaas-tenants', { page_size: 100 }).catch(() => ({ items: [] }))
  tenantUsers.value = flattenTenantAdmins(resp.items || [])
}

function onTenantUserChange(key: string) {
  const user = tenantUsers.value.find((item) => item.key === key)
  callForm.tenantId = user?.tenantId || ''
  tenantPassword.value = ''
}

async function fetchTenantUserToken() {
  const user = tenantUsers.value.find((item) => item.key === selectedTenantUserKey.value)
  if (!user) {
    ElMessage.warning('请先选择租户管理员')
    return
  }
  if (!tenantPassword.value.trim()) {
    ElMessage.warning('请填写租户管理员密码')
    return
  }
  tokenLoading.value = true
  try {
    const resp = await apiPost<{
      token: string
      fingerprint?: string
      tenant_id?: string
      app_api_ok?: boolean
      app_api_error?: string
    }>('/mcp-platform/apaas-user-token', {
      tenant_id: user.tenantId,
      account: user.account,
      password: tenantPassword.value,
    })
    callForm.apaasToken = resp.token || ''
    callForm.tenantId = resp.tenant_id || user.tenantId
    if (resp.app_api_ok === false) {
      ElMessage.warning(`Token 已获取，但 aPaaS 应用接口探测失败：${resp.app_api_error || '未知错误'}`)
    } else {
      ElMessage.success(`已获取租户用户 Token：${resp.fingerprint || '成功'}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '获取 Token 失败')
  } finally {
    tokenLoading.value = false
  }
}

async function callTool() {
  if (!callForm.apaasToken.trim() || !callForm.tenantId.trim()) {
    ElMessage.warning('调用工具需要填写 aPaaS 用户凭证和租户 ID')
    return
  }
  calling.value = true
  resultText.value = ''
  try {
    let args: any
    try {
      args = JSON.parse(callForm.argsJson || '{}')
    } catch {
      ElMessage.error('工具参数不是合法 JSON')
      return
    }
    if (args && typeof args === 'object' && !Array.isArray(args)) {
      for (const key of ENV_PARAM_KEYS) delete args[key]
    }
    const resp = await fetch(resolveMcpUrl(form.url), {
      method: 'POST',
      headers: headers(true),
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: Date.now(),
        method: 'tools/call',
        params: {
          name: callForm.toolName,
          arguments: args,
        },
      }),
    })
    resultText.value = await resp.text()
  } catch (err: any) {
    resultText.value = err?.message || '调用失败'
  } finally {
    calling.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadAdmins(), loadTenantUsers()])
  const access = await apiGet<{ key: string }>('/mcp-platform/mcp-access').catch(() => null)
  form.key = access?.key || ''
  const serviceCode = route.query.service
  if (typeof serviceCode === 'string' && services.some((item) => item.code === serviceCode)) {
    form.serviceCode = serviceCode
    onServiceChange(serviceCode)
    return
  }
  const url = route.query.url
  if (typeof url === 'string' && url) {
    const service = services.find((item) => item.url === resolveMcpUrl(url))
    if (service) {
      form.serviceCode = service.code
      form.url = service.url
    }
  }
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Tokens: design-v3-tokens.css (var(--brand)/--text/--surface/--line) */
/* v3 2026-05-21 — 跟 frontend 密度对齐：max-width/h1/page-header/section card 全
   交给 density-align.css 全局规则。本 scoped 只保留 layout + inline-row + result。 */
.page {
  color: var(--text);
  font-family: var(--font-sans);
}
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}
.section {
  margin-bottom: 14px;
}
.inline-row {
  display: flex;
  width: 100%;
  gap: 8px;
}
.result {
  white-space: pre-wrap;
  margin: 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  color: var(--text-2);
  background: var(--surface-3);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
  line-height: 1.6;
  max-height: 420px;
  overflow: auto;
}

/* Dark theme overrides */
html[data-theme="dark"] .section :deep(.el-card) {
  background: var(--surface);
  border-color: var(--line);
}
html[data-theme="dark"] .result {
  background: var(--surface-3);
  border-color: var(--line);
}
</style>

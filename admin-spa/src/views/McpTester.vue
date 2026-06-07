<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>MCP 测试台</h1>
        <p>使用当前平台管理登录态，直接测试 ai-builder backend 进程内注册的 MCP 工具。</p>
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
        <el-form-item label="鉴权方式">
          <el-input v-model="form.authMode" disabled />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="loadingTools" @click="() => loadTools()">获取同进程工具</el-button>
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
            暂无工具数据，请先点击「获取同进程工具」。
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
import { apiGet, apiPost } from '@/api/client'

interface ToolItem {
  name: string
  description?: string
  inputSchema?: any
}
interface ServiceItem {
  name: string
  code: string
  url: string
  tools: number
  toolNames?: string[]
}

const route = useRoute()

const services: ServiceItem[] = [
  { name: '同进程工具服务', code: 'ai-builder-inprocess', url: '/api/admin/mcp/call', tools: 111 },
  { name: '问题分诊记录 MCP', code: 'support-triage', url: '/api/support-triage-mcp/mcp', tools: 1, toolNames: ['record_support_triage'] },
]

const form = reactive({
  serviceCode: 'ai-builder-inprocess',
  url: '/api/admin/mcp/call',
  authMode: '平台管理登录态',
})

const callForm = reactive({
  toolName: '',
  argsJson: '{}',
})

const tools = ref<ToolItem[]>([])
const toolsMessage = ref('')
const resultText = ref('')
const loadingTools = ref(false)
const calling = ref(false)
// v3 2026-05-21 UED 报告 P1: 切服务时回滚用 — 记住上一次成功的 serviceCode
const lastServiceCode = ref('ai-builder-inprocess')
const selectedTool = computed(() => tools.value.find((item) => item.name === callForm.toolName))
const ENV_PARAM_KEYS = new Set(['env', 'env_id', 'alias', 'platform_env_id', 'tenant_id', 'user_id'])
const argsPlaceholder = computed(() => {
  if (!selectedTool.value?.inputSchema) return '例如：{}'
  return JSON.stringify(buildExampleFromSchema(selectedTool.value.inputSchema), null, 2)
})

async function loadTools(silent = false): Promise<boolean> {
  if (!form.url) {
    if (!silent) ElMessage.warning('请选择 MCP 服务')
    return false
  }
  loadingTools.value = true
  toolsMessage.value = silent ? '切换中…' : ''
  resultText.value = ''
  try {
    const data = await apiGet<any>('/admin/mcp/tools')
    resultText.value = JSON.stringify(data, null, 2)
    const service = services.find((item) => item.code === form.serviceCode)
    const allowList = service?.toolNames?.length ? new Set(service.toolNames) : null
    const list = allowList
      ? (data?.tools || []).filter((item: any) => allowList.has(item?.name))
      : (data?.tools || [])
    tools.value = Array.isArray(list)
      ? list.map((item: any) => ({
          name: item.name,
          description: [item.title, item.description].filter(Boolean).join('\n'),
          inputSchema: item.inputSchema || item.input_schema,
        }))
      : []
    if (tools.value.length) {
      toolsMessage.value = `获取成功，共 ${tools.value.length} 个工具`
      return true
    } else {
      toolsMessage.value = '未获取到工具列表'
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

async function callTool() {
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
    const resp = await apiPost<any>('/admin/mcp/call', {
      tool_name: callForm.toolName,
      args,
    })
    resultText.value = JSON.stringify(resp, null, 2)
  } catch (err: any) {
    resultText.value = err?.response?.data?.detail || err?.message || '调用失败'
  } finally {
    calling.value = false
  }
}

onMounted(async () => {
  const serviceCode = route.query.service
  if (typeof serviceCode === 'string' && services.some((item) => item.code === serviceCode)) {
    form.serviceCode = serviceCode
    onServiceChange(serviceCode)
    return
  }
  const url = route.query.url
  if (typeof url === 'string' && url) {
    const service = services.find((item) => item.url === url)
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

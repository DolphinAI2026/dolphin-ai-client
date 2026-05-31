<template>
  <div class="llm-page">
    <section class="llm-hero">
      <div class="llm-hero-info">
        <div class="llm-hero-title">
          <h1>模型配置</h1>
          <div class="llm-hero-badges">
            <el-tag size="small" effect="plain">{{ configs.length }} 个配置</el-tag>
            <el-tag size="small" type="success" effect="plain">{{ activeCount }} 启用</el-tag>
            <el-tag size="small" type="info" effect="plain" :title="defaultConfigLabel">默认：{{ defaultConfigLabel }}</el-tag>
          </div>
        </div>
        <p>集中维护睿鲸AI可用的大模型供应商、模型、API Key 和默认模型，前台 Builder 与 AI Coding 直接消费这里的配置。</p>
      </div>
      <div class="hero-actions">
        <el-input
          v-model="keyword"
          class="search-input"
          clearable
          placeholder="搜索供应商、模型、配置名"
          :prefix-icon="Search"
        />
        <el-button type="primary" class="primary-button" @click="openCreate">
          <el-icon><Plus /></el-icon>
          新增模型
        </el-button>
      </div>
    </section>

    <section class="model-panel">
      <div class="panel-head">
        <div>
          <strong>大模型配置</strong>
          <span>{{ filteredConfigs.length }} 个配置</span>
        </div>
        <el-button :loading="loading" @click="loadConfigs">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>

      <div v-if="!filteredConfigs.length && !loading" class="empty-state">
        <div class="empty-mark">
          <el-icon><Cpu /></el-icon>
        </div>
        <strong>{{ configs.length ? '没有匹配的模型配置' : '暂无模型配置' }}</strong>
        <p>{{ configs.length ? '换个关键词试试，或清空搜索条件。' : '新增一个模型后，睿鲸AI工作台与 AI Coding 就能使用它。' }}</p>
        <el-button v-if="!configs.length" type="primary" class="primary-button" @click="openCreate">新增模型</el-button>
      </div>

      <div v-else v-loading="loading" class="config-grid">
        <article v-for="config in filteredConfigs" :key="config.id" class="config-card">
          <div class="config-top">
            <div class="provider-mark">{{ providerShort(config.provider) }}</div>
            <div class="config-title">
              <div>
                <h2>{{ config.config_name }}</h2>
                <p>{{ providerLabel(config.provider) }} · {{ config.model }}</p>
              </div>
              <div class="tag-row">
                <span class="status-pill" :class="config.status">{{ statusLabel(config.status) }}</span>
                <span v-if="config.is_default" class="default-pill">默认</span>
              </div>
            </div>
          </div>

          <div class="config-meta">
            <div>
              <span>用途</span>
              <strong>{{ purposeLabel(config.purpose) }}</strong>
            </div>
            <div>
              <span>Max Tokens</span>
              <strong>{{ config.max_tokens }}</strong>
            </div>
            <div>
              <span>Temperature</span>
              <strong>{{ config.temperature }}</strong>
            </div>
          </div>

          <div class="base-url">
            <span>接入地址</span>
            <code>{{ config.base_url }}</code>
          </div>

          <div class="config-actions">
            <el-button :loading="testingId === config.id" @click="testConfig(config)">
              <el-icon><Lightning /></el-icon>
              测试
            </el-button>
            <el-button :disabled="config.is_default || config.status !== 'active'" @click="setDefault(config)">
              设为默认
            </el-button>
            <el-button @click="toggleStatus(config)">
              {{ config.status === 'active' ? '禁用' : '启用' }}
            </el-button>
            <el-button @click="openEdit(config)">编辑</el-button>
            <el-button type="danger" plain @click="removeConfig(config)">删除</el-button>
          </div>
        </article>
      </div>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="editingConfig ? '编辑模型配置' : '新增模型配置'"
      width="720px"
      destroy-on-close
      class="llm-dialog"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="form-grid">
          <el-form-item label="配置名称" prop="config_name">
            <el-input v-model="form.config_name" placeholder="例如：内置通用模型" />
          </el-form-item>
          <el-form-item label="供应商" prop="provider">
            <el-select v-model="form.provider" filterable @change="applyProviderPreset">
              <el-option
                v-for="item in providerOptions"
                :key="item.provider"
                :label="item.label"
                :value="item.provider"
              />
            </el-select>
          </el-form-item>
        </div>

        <el-form-item label="接入地址" prop="base_url">
          <el-input v-model="form.base_url" placeholder="https://api.example.com/v1" />
        </el-form-item>

        <el-form-item :label="editingConfig ? 'API Key（留空则不修改；拉取模型时必填）' : 'API Key'" prop="api_key">
          <el-input v-model="form.api_key" type="password" show-password placeholder="请先输入模型服务 API Key" />
        </el-form-item>

        <div class="form-grid">
          <el-form-item label="模型" prop="model">
            <el-select v-model="form.model" filterable allow-create default-first-option placeholder="请先填写 API Key 并拉取模型">
              <el-option v-for="model in currentModels" :key="model" :label="model" :value="model" />
            </el-select>
            <el-button class="fetch-models-button" :loading="fetchingModels" @click="fetchModels">
              拉取模型
            </el-button>
          </el-form-item>
          <el-form-item label="用途" prop="purpose">
            <el-select v-model="form.purpose">
              <el-option label="全部场景" value="all" />
              <el-option label="睿鲸AI工作台" value="builder" />
              <el-option label="AI Coding" value="coding" />
            </el-select>
          </el-form-item>
        </div>

        <div class="form-grid form-grid-three">
          <el-form-item label="Max Tokens" prop="max_tokens">
            <!-- 2026-05-21 上限从 200000 (200K) 提到 2000000 (2M)
                 现 Claude Sonnet 4.6 / gpt-5.x 都支持 1M context，
                 留 2M buffer 防未来模型再翻倍。step 1024 不再 512 以适应大值。 -->
            <el-input-number v-model="form.max_tokens" :min="512" :max="2000000" :step="1024" controls-position="right" />
          </el-form-item>
          <el-form-item label="Temperature" prop="temperature">
            <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" controls-position="right" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="form.status" :disabled="!editingConfig">
              <el-option label="启用" value="active" />
              <el-option label="禁用" value="inactive" />
            </el-select>
          </el-form-item>
        </div>

        <el-form-item>
          <el-switch v-model="form.is_default" active-text="设为默认模型" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" class="primary-button" :loading="saving" @click="saveConfig">保存配置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Cpu, Lightning, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { apiDel, apiGet, apiPost, apiPut } from '@/api/client'

type ConfigStatus = 'active' | 'inactive' | 'error'

interface LlmConfig {
  id: number
  config_name: string
  provider: string
  base_url: string
  model: string
  purpose: string
  is_default: boolean
  max_tokens: number
  temperature: number
  status: ConfigStatus
  created_at?: string
  updated_at?: string
}

interface PresetValue {
  base_url: string
  models: string[]
}

interface ProviderOption extends PresetValue {
  provider: string
  label: string
}

interface LlmForm {
  config_name: string
  provider: string
  base_url: string
  api_key: string
  model: string
  purpose: string
  is_default: boolean
  max_tokens: number
  temperature: number
  status: ConfigStatus
}

const providerLabels: Record<string, string> = {
  dolphin: 'Dolphin',
  minimax: 'MiniMax',
  qwen: '通义千问',
  deepseek: 'DeepSeek',
  zhipu: '智谱',
  moonshot: 'Moonshot',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
}

const configs = ref<LlmConfig[]>([])
const presets = ref<Record<string, PresetValue>>({})
const keyword = ref('')
const loading = ref(false)
const saving = ref(false)
const fetchingModels = ref(false)
const testingId = ref<number | null>(null)
const dialogVisible = ref(false)
const editingConfig = ref<LlmConfig | null>(null)
const formRef = ref<FormInstance>()
const fetchedModels = ref<string[]>([])

const defaultForm: LlmForm = {
  config_name: '',
  provider: 'dolphin',
  base_url: 'http://ai-agent.dfy.definesys.cn/omnigate/0',
  api_key: '',
  model: '',
  purpose: 'all',
  is_default: false,
  max_tokens: 8192,
  temperature: 0.3,
  status: 'active',
}

const form = reactive<LlmForm>({ ...defaultForm })

const rules = computed<FormRules<LlmForm>>(() => ({
  config_name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  provider: [{ required: true, message: '请选择供应商', trigger: 'change' }],
  base_url: [{ required: true, message: '请输入接入地址', trigger: 'blur' }],
  model: [{ required: true, message: '请选择或输入模型', trigger: 'change' }],
  purpose: [{ required: true, message: '请选择用途', trigger: 'change' }],
  api_key: editingConfig.value ? [] : [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
  max_tokens: [{ required: true, message: '请输入 Max Tokens', trigger: 'change' }],
  temperature: [{ required: true, message: '请输入 Temperature', trigger: 'change' }],
}))

const providerOptions = computed<ProviderOption[]>(() => {
  return Object.entries(presets.value).map(([provider, value]) => ({
    provider,
    label: providerLabels[provider] || provider,
    base_url: value.base_url,
    models: value.models || [],
  }))
})

const currentModels = computed(() => fetchedModels.value)

const filteredConfigs = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return configs.value
  return configs.value.filter((item) => {
    return [item.config_name, item.provider, item.model, item.base_url, item.purpose]
      .some((value) => String(value || '').toLowerCase().includes(text))
  })
})

const activeCount = computed(() => configs.value.filter((item) => item.status === 'active').length)
const defaultConfig = computed(() => configs.value.find((item) => item.is_default))
const defaultConfigLabel = computed(() => {
  const config = defaultConfig.value
  if (!config) return '未设置'
  return `${config.config_name} · ${config.model}`
})

function assignForm(value: Partial<LlmForm>) {
  Object.assign(form, { ...defaultForm, ...value })
}

function providerLabel(provider: string) {
  return providerLabels[provider] || provider
}

function providerShort(provider: string) {
  return providerLabel(provider).slice(0, 2).toUpperCase()
}

function purposeLabel(purpose: string) {
  const map: Record<string, string> = {
    all: '全部场景',
    builder: '睿鲸AI工作台',
    coding: 'AI Coding',
  }
  return map[purpose] || purpose
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    active: '已启用',
    inactive: '已禁用',
    error: '异常',
  }
  return map[status] || status
}

function errorMessage(error: unknown, fallback: string) {
  const err = error as { response?: { data?: { detail?: string } }; message?: string }
  return err?.response?.data?.detail || err?.message || fallback
}

async function loadPresets() {
  presets.value = await apiGet<Record<string, PresetValue>>('/llm-configs/presets').catch(() => ({
    dolphin: {
      base_url: defaultForm.base_url,
      models: ['gpt-5.5', 'gpt-5.4', 'gpt-5.3-codex'],
    },
  }))
}

async function loadConfigs() {
  loading.value = true
  try {
    const list = await apiGet<LlmConfig[]>('/llm-configs')
    configs.value = Array.isArray(list) ? list : []
  } catch (error) {
    configs.value = []
    ElMessage.error(errorMessage(error, '加载模型配置失败'))
  } finally {
    loading.value = false
  }
}

function applyProviderPreset() {
  const preset = presets.value[form.provider]
  if (!preset) return
  form.base_url = preset.base_url || form.base_url
  form.model = ''
  fetchedModels.value = []
}

function openCreate() {
  editingConfig.value = null
  assignForm(defaultForm)
  fetchedModels.value = []
  applyProviderPreset()
  dialogVisible.value = true
}

function openEdit(config: LlmConfig) {
  editingConfig.value = config
  assignForm({
    config_name: config.config_name,
    provider: config.provider,
    base_url: config.base_url,
    api_key: '',
    model: config.model,
    purpose: config.purpose,
    is_default: config.is_default,
    max_tokens: config.max_tokens,
    temperature: config.temperature,
    status: config.status,
  })
  fetchedModels.value = []
  dialogVisible.value = true
}

async function fetchModels() {
  const apiKey = form.api_key.trim()
  if (!apiKey) {
    ElMessage.warning('请先填写 API Key，再拉取模型')
    return
  }
  if (!form.base_url.trim()) {
    ElMessage.warning('请先填写接入地址')
    return
  }

  fetchingModels.value = true
  try {
    const resp = await apiPost<{ models: string[] }>('/llm-configs/models', {
      provider: form.provider,
      base_url: form.base_url,
      api_key: apiKey,
    })
    fetchedModels.value = Array.isArray(resp.models) ? resp.models : []
    if (!fetchedModels.value.length) {
      ElMessage.warning('未拉取到可用模型，请检查服务地址和 API Key')
      return
    }
    if (!fetchedModels.value.includes(form.model)) {
      form.model = fetchedModels.value[0]
    }
    ElMessage.success(`已拉取 ${fetchedModels.value.length} 个模型`)
  } catch (error) {
    fetchedModels.value = []
    ElMessage.error(errorMessage(error, '拉取模型失败'))
  } finally {
    fetchingModels.value = false
  }
}

async function saveConfig() {
  await formRef.value?.validate()
  saving.value = true
  try {
    const payload: Partial<LlmForm> = { ...form }
    if (editingConfig.value && !payload.api_key) delete payload.api_key
    if (!editingConfig.value) delete payload.status

    if (editingConfig.value) {
      await apiPut<LlmConfig>(`/llm-configs/${editingConfig.value.id}`, payload)
      ElMessage.success('模型配置已更新')
    } else {
      await apiPost<LlmConfig>('/llm-configs', payload)
      ElMessage.success('模型配置已新增')
    }
    dialogVisible.value = false
    await loadConfigs()
  } catch (error) {
    ElMessage.error(errorMessage(error, '保存模型配置失败'))
  } finally {
    saving.value = false
  }
}

async function testConfig(config: LlmConfig) {
  testingId.value = config.id
  try {
    const resp = await apiPost<{ success: boolean; reply?: string; error?: string }>(`/llm-configs/${config.id}/test`)
    if (resp.success) {
      ElMessage.success(`测试通过${resp.reply ? `：${resp.reply}` : ''}`)
    } else {
      ElMessage.error(resp.error || '模型测试失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error, '模型测试失败'))
  } finally {
    testingId.value = null
  }
}

async function setDefault(config: LlmConfig) {
  try {
    await apiPost<LlmConfig>(`/llm-configs/${config.id}/set-default`)
    ElMessage.success('已设为默认模型')
    await loadConfigs()
  } catch (error) {
    ElMessage.error(errorMessage(error, '设置默认模型失败'))
  }
}

async function toggleStatus(config: LlmConfig) {
  const nextStatus: ConfigStatus = config.status === 'active' ? 'inactive' : 'active'
  try {
    await apiPost<LlmConfig>(`/llm-configs/${config.id}/status`, { status: nextStatus })
    ElMessage.success(nextStatus === 'active' ? '模型已启用' : '模型已禁用')
    await loadConfigs()
  } catch (error) {
    ElMessage.error(errorMessage(error, '更新模型状态失败'))
  }
}

async function removeConfig(config: LlmConfig) {
  try {
    await ElMessageBox.confirm(
      `确认删除「${config.config_name}」？此操作不可撤销，删除后前台将无法再选择该模型。`,
      '删除模型配置',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
        type: 'warning',
      },
    )
    await apiDel(`/llm-configs/${config.id}`)
    ElMessage.success('模型配置已删除')
    await loadConfigs()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(errorMessage(error, '删除模型配置失败'))
  }
}

onMounted(async () => {
  await loadPresets()
  await loadConfigs()
})
</script>

<style scoped>
/* v3 2026-05-21 — LlmConfigs 跟 frontend 密度对齐重写：
   v2 紫色 hex (#5750d8 / #766bf1) + 自定义 font-weight 760/820 全清掉，
   改 var(--brand) + var(--fw-*) + v3 typography scale (14/13.5/12.5/11)。 */
.llm-page {
  color: var(--text);
  font-family: var(--font-sans);
}

.llm-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.llm-hero p {
  color: var(--text-3);
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.search-input {
  width: 260px;
}

.primary-button {
  /* density-align.css 全局已统一 .el-button--primary 样式 — 这里只调宽度 */
  font-weight: var(--fw-medium, 500);
}

.llm-hero-info {
  min-width: 0;
  flex: 1;
}

.llm-hero-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.llm-hero-badges {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.llm-hero-badges :deep(.el-tag) {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-panel {
  overflow: hidden;
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

.panel-head {
  /* density-align.css 全局已统一 min-height/padding/title — 这里只需要 display */
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--line);
}

.config-grid {
  min-height: 200px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  padding: 16px;
}

.config-card {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.config-card:hover {
  border-color: var(--brand-ring);
  box-shadow: var(--sh-1);
}

.config-top {
  display: flex;
  gap: 12px;
}

.provider-mark {
  flex: 0 0 auto;
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: var(--r-2, 6px);
  color: var(--text-inverse, #fff);
  background: var(--brand);
  font-size: 13px;
  font-weight: var(--fw-bold, 700);
}

.config-title {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.config-title h2 {
  margin: 0;
  color: var(--text);
  font-size: 14px;
  line-height: 1.25;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: -0.005em;
}

.config-title p {
  margin: 3px 0 0;
  overflow: hidden;
  color: var(--text-3);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.status-pill,
.default-pill {
  padding: 2px 7px;
  border-radius: var(--r-1, 4px);
  font-size: 10.5px;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.status-pill.active {
  color: var(--ok);
  background: var(--ok-soft);
}

.status-pill.inactive {
  color: var(--warn);
  background: var(--warn-soft);
}

.status-pill.error {
  color: var(--err);
  background: var(--err-soft);
}

.default-pill {
  color: var(--brand);
  background: var(--brand-soft);
}

.config-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.config-meta div {
  min-width: 0;
  padding: 8px 10px;
  border-radius: var(--r-2, 6px);
  background: var(--surface-2);
}

.config-meta span,
.base-url span {
  display: block;
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: var(--fw-medium, 500);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.config-meta strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.base-url {
  min-width: 0;
}

code {
  display: block;
  min-width: 0;
  margin-top: 4px;
  overflow: hidden;
  color: var(--text-2);
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
  font-size: 11.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.config-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding-top: 4px;
}

/* density-align.css 已统一 .el-button — 这里 cardconfig 内的按钮再收一档 */
.config-actions :deep(.el-button) {
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
}

.empty-state {
  min-height: 280px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  padding: 32px;
  text-align: center;
}

.empty-mark {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: var(--r-3, 8px);
  color: var(--brand);
  background: var(--brand-soft);
  font-size: 20px;
}

.empty-state strong {
  color: var(--text);
  font-size: 14.5px;
  font-weight: var(--fw-semibold, 600);
}

.empty-state p {
  margin: 0;
  color: var(--text-3);
  font-size: 13px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.form-grid-three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.llm-dialog :deep(.el-input-number) {
  width: 100%;
}

.fetch-models-button {
  margin-top: 8px;
}

@media (max-width: 1180px) {
  .llm-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .hero-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .search-input {
    width: min(100%, 360px);
  }

  .config-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .form-grid,
  .form-grid-three,
  .config-meta {
    grid-template-columns: 1fr;
  }
}
</style>

<template>
  <div class="llm-page">
    <section class="llm-hero">
      <div>
        <h1>模型配置</h1>
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

    <section class="summary-grid">
      <article v-for="item in summaryCards" :key="item.label" class="summary-card">
        <div class="summary-icon" :class="item.tone">
          <el-icon><component :is="item.icon" /></el-icon>
        </div>
        <div>
          <span>{{ item.label }}</span>
          <strong :title="item.value">{{ item.value }}</strong>
        </div>
      </article>
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
        <p>{{ configs.length ? '换个关键词试试，或清空搜索条件。' : '新增一个模型后，AI Builder 与 AI Coding 就能使用它。' }}</p>
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

        <div class="form-grid">
          <el-form-item label="模型" prop="model">
            <el-select v-model="form.model" filterable allow-create default-first-option placeholder="选择或输入模型">
              <el-option v-for="model in currentModels" :key="model" :label="model" :value="model" />
            </el-select>
          </el-form-item>
          <el-form-item label="用途" prop="purpose">
            <el-select v-model="form.purpose">
              <el-option label="全部场景" value="all" />
              <el-option label="AI Builder" value="builder" />
              <el-option label="AI Coding" value="coding" />
            </el-select>
          </el-form-item>
        </div>

        <el-form-item :label="editingConfig ? 'API Key（留空则不修改）' : 'API Key'" prop="api_key">
          <el-input v-model="form.api_key" type="password" show-password placeholder="请输入模型服务 API Key" />
        </el-form-item>

        <div class="form-grid form-grid-three">
          <el-form-item label="Max Tokens" prop="max_tokens">
            <el-input-number v-model="form.max_tokens" :min="512" :max="200000" :step="512" controls-position="right" />
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
import { computed, markRaw, onMounted, reactive, ref } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, Cpu, Lightning, Plus, Refresh, Search, Star } from '@element-plus/icons-vue'
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
const testingId = ref<number | null>(null)
const dialogVisible = ref(false)
const editingConfig = ref<LlmConfig | null>(null)
const formRef = ref<FormInstance>()

const defaultForm: LlmForm = {
  config_name: '',
  provider: 'dolphin',
  base_url: 'http://ai-agent.dfy.definesys.cn/omnigate/0',
  api_key: '',
  model: 'gpt-5.5',
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

const currentModels = computed(() => presets.value[form.provider]?.models || [])

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

const summaryCards = computed(() => [
  { label: '模型配置', value: `${configs.value.length} 个`, tone: 'tone-purple', icon: markRaw(Cpu) },
  { label: '启用中', value: `${activeCount.value} 个`, tone: 'tone-green', icon: markRaw(CircleCheck) },
  { label: '默认模型', value: defaultConfigLabel.value, tone: 'tone-blue', icon: markRaw(Star) },
])

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
    builder: 'AI Builder',
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
  if (!preset.models.includes(form.model)) {
    form.model = preset.models[0] || form.model
  }
}

function openCreate() {
  editingConfig.value = null
  assignForm(defaultForm)
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
  dialogVisible.value = true
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
    await ElMessageBox.confirm(`确认删除「${config.config_name}」？删除后前台将无法再选择该模型。`, '删除模型配置', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
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
.llm-page {
  max-width: 1440px;
  margin: 0 auto;
  padding: 8px 0 56px;
  color: #17162f;
}

.llm-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 22px;
}

h1 {
  margin: 0;
  font-size: 32px;
  line-height: 1.2;
  font-weight: 820;
}

.llm-hero p {
  max-width: 940px;
  margin: 14px 0 0;
  color: #5f5a7c;
  font-size: 16px;
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.search-input {
  width: 280px;
}

.primary-button {
  border: 0;
  border-radius: 10px;
  font-weight: 760;
  background: linear-gradient(180deg, #766bf1, #5750d8);
  box-shadow: 0 14px 28px rgba(87, 80, 216, 0.24);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 20px;
}

.summary-card {
  min-height: 94px;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border: 1px solid #ded9eb;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 24px rgba(34, 30, 70, 0.07);
}

.summary-card > div:last-child {
  min-width: 0;
}

.summary-icon {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  font-size: 19px;
}

.summary-card span {
  display: block;
  color: #8a85a5;
  font-size: 14px;
  font-weight: 720;
}

.summary-card strong {
  display: block;
  margin-top: 6px;
  color: #17162f;
  font-size: 22px;
  line-height: 1.1;
  font-weight: 820;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tone-green { color: #13a778; background: #eaf8f3; }
.tone-purple { color: #5750d8; background: #efedff; }
.tone-blue { color: #1889c7; background: #eaf5ff; }

.model-panel {
  overflow: hidden;
  border: 1px solid #ded9eb;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 24px rgba(34, 30, 70, 0.07);
}

.panel-head {
  min-height: 62px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 22px;
  border-bottom: 1px solid #ece8f6;
  background: #f3f0fb;
}

.panel-head strong {
  color: #17162f;
  font-size: 17px;
  font-weight: 820;
}

.panel-head span {
  margin-left: 10px;
  color: #8a85a5;
  font-size: 13px;
  font-weight: 700;
}

.config-grid {
  min-height: 260px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  padding: 22px;
}

.config-card {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px;
  border: 1px solid #e4dff0;
  border-radius: 14px;
  background: #fff;
}

.config-top {
  display: flex;
  gap: 14px;
}

.provider-mark {
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: #fff;
  background: linear-gradient(180deg, #766bf1, #5750d8);
  box-shadow: 0 12px 24px rgba(87, 80, 216, 0.18);
  font-weight: 820;
}

.config-title {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.config-title h2 {
  margin: 0;
  color: #17162f;
  font-size: 18px;
  line-height: 1.25;
  font-weight: 820;
}

.config-title p {
  margin: 6px 0 0;
  overflow: hidden;
  color: #7a719d;
  font-size: 13px;
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
  padding: 4px 9px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 760;
  white-space: nowrap;
}

.status-pill.active {
  color: #159f78;
  background: #effaf7;
}

.status-pill.inactive {
  color: #dd7a13;
  background: #fff1e5;
}

.status-pill.error {
  color: #f04444;
  background: #fff0f0;
}

.default-pill {
  color: #5146d8;
  background: #eeeaff;
}

.config-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.config-meta div {
  min-width: 0;
  padding: 12px;
  border-radius: 10px;
  background: #f8f6fd;
}

.config-meta span,
.base-url span {
  display: block;
  color: #8a85a5;
  font-size: 12px;
  font-weight: 720;
}

.config-meta strong {
  display: block;
  margin-top: 5px;
  overflow: hidden;
  color: #17162f;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.base-url {
  min-width: 0;
}

code {
  display: block;
  min-width: 0;
  margin-top: 6px;
  overflow: hidden;
  color: #7a719d;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.config-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 4px;
}

.empty-state {
  min-height: 360px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  padding: 40px;
  text-align: center;
}

.empty-mark {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  color: #5750d8;
  background: #efedff;
  font-size: 22px;
}

.empty-state strong {
  color: #17162f;
  font-size: 18px;
  font-weight: 820;
}

.empty-state p {
  margin: 0;
  color: #8a85a5;
  font-size: 14px;
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

  .summary-grid,
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

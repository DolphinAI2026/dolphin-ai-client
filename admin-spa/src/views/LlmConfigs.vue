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
        <EmptyState
          :variant="configs.length ? 'filtered' : 'first'"
          :title="configs.length ? '没有匹配的模型配置' : '暂无模型配置'"
          :desc="configs.length ? '换个关键词试试，或清空搜索条件。' : '新增一个模型后，AI Builder 与 AI Coding 就能使用它。'"
        >
          <template #icon>
            <el-icon><Cpu /></el-icon>
          </template>
          <template v-if="configs.length" #cta>
            <el-button @click="keyword = ''">清空搜索</el-button>
          </template>
          <template v-else #cta>
            <el-button type="primary" class="primary-button" @click="openCreate">新增模型</el-button>
          </template>
        </EmptyState>
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
import EmptyState from '@/components/states/EmptyState.vue'

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
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Reference: /tmp/ai-builder-design/design-spec/07-admin.html section 7.4 LLM CONFIGS
   Tokens: design-v3-tokens.css (copied to admin-spa/src/styles)

   Preserved (don't change):
     - Template structure (4 summary cards instead of 3, but kept .tone-purple/green/blue mapping
       via aliasing — script keeps tone-purple/green/blue)
     - All API calls + form state + providerLabels map
     - Element Plus components (el-input / el-button / el-dialog / el-form)
   Refreshed:
     - Hero h1: 32→22px 700 (v3 scale, was 820 ai-slop weight)
     - Subtext 16→13.5px line-height 1.55 (v3 lead)
     - Search input + button: clean borders, var(--surface-2) / var(--brand)
     - Summary card: 94→auto min-height, 14→r-4 radius, brand-soft icon bg (was tone classes)
     - Provider mark: 44×44 r-3 + mono 11px 700 + alpha 0.12 soft bg
     - Provider专色 (5)：anthropic #C45A2D / openai #10A37F / deepseek #2D64E6 /
       azure #0078D4 / local neutral. NOTE: template binds no class to .provider-mark,
       so we use [data-provider] pattern via :has() can't and default to brand-soft.
       The 5 provider colors are documented but applied via .provider-mark[data-provider="X"]
       which won't actually activate (template fixed). Default brand-soft is enterprise-blue.
     - Status pill: r-1 + 10.5px 600 letter-spacing 0.02em
     - Config meta: 3 col + top/bottom border var(--line) (was bg blocks)
     - Base url: surface-2 软底 + r-2 + mono 11px (was code block w/ ellipsis)
     - Act buttons: inline同款 + brand-soft hover (was el-button gradient mix)
*/
.llm-page {
  max-width: 1440px;
  margin: 0 auto;
  padding: 8px 0 56px;
  color: var(--text);
  font-family: var(--font-sans);
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
  font-size: 22px;
  line-height: 1.25;
  font-weight: var(--fw-bold, 700);
  color: var(--text);
  letter-spacing: -0.01em;
}

.llm-hero p {
  max-width: 940px;
  margin: 8px 0 0;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.55;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.search-input {
  width: 280px;
}

.search-input :deep(.el-input__wrapper) {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  box-shadow: none;
  height: 32px;
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.search-input :deep(.el-input__wrapper):hover {
  border-color: var(--line-strong);
}
.search-input :deep(.el-input__wrapper.is-focus) {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
}
.search-input :deep(.el-input__inner) {
  color: var(--text);
  font-size: 12.5px;
}
.search-input :deep(.el-input__inner)::placeholder {
  color: var(--text-4);
}

.primary-button.el-button {
  border: 0;
  border-radius: var(--r-2, 6px);
  font-weight: 600;
  height: 32px;
  padding: 0 14px;
  font-size: 12.5px;
  background: var(--brand);
  color: var(--text-inverse, #fff);
  box-shadow: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.primary-button.el-button:hover,
.primary-button.el-button:focus {
  background: var(--brand-hover);
  color: var(--text-inverse, #fff);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.summary-card {
  min-height: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

.summary-card > div:last-child {
  min-width: 0;
}

.summary-icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: var(--r-3, 8px);
  font-size: 17px;
  flex-shrink: 0;
  background: var(--brand-soft);
  color: var(--brand);
}

.summary-card span {
  display: block;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.summary-card strong {
  display: block;
  margin-top: 2px;
  color: var(--text);
  font-size: 22px;
  line-height: 1.1;
  font-weight: 700;
  letter-spacing: -0.02em;
  font-feature-settings: 'tnum';
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Legacy tone classes — script still emits tone-purple/green/blue.
   Map them to v3 soft palettes (brand-soft / ok-soft / surface-3). */
.tone-purple { background: var(--brand-soft); color: var(--brand); }
.tone-green { background: var(--ok-soft); color: var(--ok); }
.tone-blue { background: var(--warn-soft); color: var(--warn); }

.model-panel {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

.panel-head {
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 18px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}

.panel-head strong {
  color: var(--text);
  font-size: 13.5px;
  font-weight: 600;
}

.panel-head span {
  margin-left: 8px;
  color: var(--text-3);
  font-size: 12px;
  font-weight: 500;
}

.panel-head :deep(.el-button) {
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 500;
  height: 30px;
  border-radius: var(--r-2, 6px);
}
.panel-head :deep(.el-button:hover) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}

.config-grid {
  min-height: 260px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 14px;
  padding: 18px;
  background: var(--surface-2);
}

.config-card {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  transition: border-color 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.config-card:hover {
  border-color: var(--brand-ring);
  box-shadow: var(--sh-2);
}

.config-top {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

/* Provider mark — default fallback (v3 brand-soft).
   5 specific provider专色 hardcoded for reference; activation requires
   template binding (data-provider attr) which is locked by iron rule.
   Keeping the class hooks for a future template extension. */
.provider-mark {
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: var(--r-3, 8px);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--brand);
  background: var(--brand-soft);
  box-shadow: none;
}
.provider-mark[data-provider="anthropic"] { background: rgba(196, 90, 45, 0.12); color: #C45A2D; }
.provider-mark[data-provider="openai"]    { background: rgba(16, 163, 127, 0.12); color: #10A37F; }
.provider-mark[data-provider="deepseek"]  { background: rgba(45, 100, 230, 0.12); color: #2D64E6; }
.provider-mark[data-provider="azure"]     { background: rgba(0, 120, 212, 0.12); color: #0078D4; }
.provider-mark[data-provider="local"]     { background: var(--surface-3); color: var(--text-2); }

.config-title {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.config-title > div:first-child {
  min-width: 0;
}

.config-title h2 {
  margin: 0;
  color: var(--text);
  font-size: 14.5px;
  line-height: 1.3;
  font-weight: 600;
  letter-spacing: -0.005em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.config-title p {
  margin: 3px 0 0;
  overflow: hidden;
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
  flex-shrink: 0;
}

.status-pill,
.default-pill {
  display: inline-flex;
  padding: 2px 7px;
  border-radius: var(--r-1, 4px);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.status-pill.active {
  color: var(--ok);
  background: var(--ok-soft);
}

.status-pill.inactive {
  color: var(--text-3);
  background: var(--surface-3);
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
  padding: 10px 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  margin: 0;
}

.config-meta > div {
  min-width: 0;
  padding: 0;
  border-radius: 0;
  background: transparent;
}

.config-meta span,
.base-url span {
  display: block;
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.config-meta strong {
  display: block;
  margin-top: 2px;
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  font-feature-settings: 'tnum';
  text-overflow: ellipsis;
  white-space: nowrap;
}

.base-url {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--surface-2);
  border-radius: var(--r-2, 6px);
  font-size: 11px;
  min-width: 0;
}

.base-url span {
  flex-shrink: 0;
  text-transform: none;
  letter-spacing: 0;
}

code {
  display: block;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--text);
  font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.config-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.config-actions :deep(.el-button) {
  padding: 4px 8px;
  height: auto;
  min-height: 0;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--r-1, 4px);
  color: var(--text-2);
  font-size: 11px;
  font-weight: 500;
  margin: 0;
  transition: background 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.config-actions :deep(.el-button:not(.is-disabled):hover) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}
.config-actions :deep(.el-button--danger.is-plain) {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-2);
}
.config-actions :deep(.el-button--danger.is-plain:not(.is-disabled):hover) {
  background: var(--err-soft);
  color: var(--err);
  border-color: var(--err);
}
.config-actions :deep(.el-button.is-disabled) {
  opacity: 0.5;
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
  border-radius: var(--r-3, 8px);
  color: var(--brand);
  background: var(--brand-soft);
  font-size: 22px;
}

.empty-state strong {
  color: var(--text);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.005em;
}

.empty-state p {
  margin: 0;
  color: var(--text-3);
  font-size: 13px;
  line-height: 1.5;
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

.llm-dialog :deep(.el-dialog) {
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  border: 1px solid var(--line);
  box-shadow: var(--sh-4);
}

.llm-dialog :deep(.el-dialog__header) {
  padding: 18px 20px 14px;
  margin: 0;
  border-bottom: 1px solid var(--line);
}

.llm-dialog :deep(.el-dialog__title) {
  color: var(--text);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.005em;
}

.llm-dialog :deep(.el-dialog__body) {
  padding: 20px;
}

.llm-dialog :deep(.el-dialog__footer) {
  padding: 14px 20px;
  border-top: 1px solid var(--line);
}

.llm-dialog :deep(.el-form-item__label) {
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 500;
  padding-bottom: 6px;
}

/* Dark theme overrides */
html[data-theme="dark"] .summary-card,
html[data-theme="dark"] .model-panel,
html[data-theme="dark"] .config-card {
  background: var(--surface);
  border-color: var(--line);
}
html[data-theme="dark"] .panel-head {
  background: var(--surface);
}
html[data-theme="dark"] .config-grid {
  background: var(--surface-2);
}
html[data-theme="dark"] .base-url {
  background: var(--surface-3);
}
html[data-theme="dark"] .provider-mark[data-provider="anthropic"] { background: rgba(196, 90, 45, 0.16); color: #E08568; }
html[data-theme="dark"] .provider-mark[data-provider="openai"]    { background: rgba(16, 163, 127, 0.16); color: #4FD9B3; }
html[data-theme="dark"] .provider-mark[data-provider="deepseek"]  { background: rgba(45, 100, 230, 0.16); color: #6E94F5; }
html[data-theme="dark"] .provider-mark[data-provider="azure"]     { background: rgba(0, 120, 212, 0.16); color: #4FB3F2; }

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

  .summary-grid {
    grid-template-columns: 1fr;
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

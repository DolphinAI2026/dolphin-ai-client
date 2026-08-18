<template>
  <div class="local-model-settings">
    <div class="local-model-toolbar">
      <span>{{ configs.length ? `已配置 ${configs.length} 个模型` : '还没有可供本机使用的模型' }}</span>
      <div>
        <el-button :loading="loading" @click="loadConfigs"><AppIcon name="refresh" :size="14" />刷新</el-button>
        <el-button type="primary" @click="openCreate"><AppIcon name="plus" :size="14" />新增模型</el-button>
      </div>
    </div>

    <div v-if="loading" class="local-model-empty">正在读取本机模型配置…</div>
    <div v-else-if="!configs.length" class="local-model-empty">
      <AppIcon name="bot" :size="25" />
      <strong>暂无本地模型</strong>
      <span>新增后可供这台客户端的 Builder 和 Code 使用。</span>
      <el-button type="primary" @click="openCreate">新增第一个模型</el-button>
    </div>
    <div v-else class="local-model-list">
      <article v-for="config in configs" :key="config.id" class="local-model-row">
        <div class="model-status" :class="config.status" />
        <div class="model-main">
          <div class="model-title">
            <strong>{{ config.config_name }}</strong>
            <el-tag v-if="config.is_default" size="small" type="success" effect="plain">默认</el-tag>
            <el-tag v-if="config.codex_wire_api === 'chat'" size="small" type="warning" effect="plain">Chat 兼容</el-tag>
            <el-tag v-else-if="config.status !== 'active'" size="small" type="info" effect="plain">已停用</el-tag>
          </div>
          <span>{{ providerLabel(config.provider) }} · {{ config.model }} · {{ purposeLabel(config.purpose) }}</span>
        </div>
        <div class="model-actions">
          <el-button text size="small" :loading="config._testing" @click="testConfig(config)">测试</el-button>
          <el-button text size="small" @click="toggleStatus(config)">{{ config.status === 'active' ? '停用' : '启用' }}</el-button>
          <el-button v-if="!config.is_default && config.status === 'active'" text size="small" @click="setDefault(config)">设默认</el-button>
          <el-button text size="small" @click="openEdit(config)">编辑</el-button>
          <el-button class="delete-action" plain size="small" @click="deleteConfig(config)">删除</el-button>
        </div>
      </article>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑本地模型' : '新增本地模型'" width="560px" :close-on-click-modal="false" append-to-body>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="配置名称" required><el-input v-model="form.config_name" placeholder="例如：DeepSeek 主力模型" /></el-form-item>
        <el-form-item label="供应商" required>
          <el-select v-model="form.provider" style="width: 100%" @change="onProviderChange">
            <el-option v-for="provider in providerOptions" :key="provider.value" :label="provider.label" :value="provider.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="API 地址" required><el-input v-model="form.base_url" placeholder="https://api.example.com/v1" /></el-form-item>
        <el-form-item label="API Key" required><el-input v-model="form.api_key" type="password" show-password :placeholder="editing ? '留空则保持不变' : '输入 API Key'" /></el-form-item>
        <el-form-item label="模型" required>
          <div class="model-picker">
          <el-autocomplete v-model="form.model" :fetch-suggestions="queryModelSuggestions" clearable placeholder="直接输入模型名，或从建议中选择" />
          <el-button :loading="fetchingModels" :disabled="!form.base_url.trim() || !form.api_key.trim()" @click="fetchModels">从 /models 获取</el-button>
          </div>
          <div class="form-tip">支持直接输入任意模型名；填写 API 地址和 Key 后，也可从服务的 <code>/models</code> 获取。</div>
        </el-form-item>
        <el-form-item label="Code 接口兼容">
          <el-radio-group v-model="form.codex_wire_api">
            <el-radio value="responses">Responses API</el-radio>
            <el-radio value="chat">Chat Completions（转换兼容）</el-radio>
          </el-radio-group>
          <div class="form-tip">仅影响 Code。模型只支持 <code>/chat/completions</code> 时选择此项。</div>
        </el-form-item>
        <div class="form-pair">
          <el-form-item label="用途"><el-select v-model="form.purpose"><el-option label="全部场景" value="all" /><el-option label="应用构建" value="builder" /><el-option label="代码生成" value="coding" /></el-select></el-form-item>
          <el-form-item label="最大输出 Tokens"><el-input-number v-model="form.max_tokens" :min="256" :max="128000" :step="256" controls-position="right" /></el-form-item>
        </div>
        <el-form-item label="Temperature"><el-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" show-input /></el-form-item>
        <el-form-item><el-switch v-model="form.is_default" active-text="设为默认模型" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">{{ editing ? '保存' : '添加' }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '@/components/common/AppIcon.vue'
import { llmConfigApi, type LlmConfig, type ProviderPreset } from '@/api/llmConfig'
import { providerLabel, providerOptions, purposeLabel } from '@/utils/llmConfig'

interface ModelWithState extends LlmConfig { _testing?: boolean }

const configs = ref<ModelWithState[]>([])
const presets = ref<ProviderPreset[]>([])
const loading = ref(false)
const saving = ref(false)
const fetchingModels = ref(false)
const dialogVisible = ref(false)
const editing = ref<LlmConfig | null>(null)
const form = reactive({ config_name: '', provider: 'minimax', base_url: '', api_key: '', model: '', purpose: 'all', max_tokens: 4096, temperature: 0.7, is_default: false, codex_wire_api: 'responses' as 'responses' | 'chat' })
const fetchedModels = ref<string[]>([])
const modelOptions = computed(() => [...new Set([...(presets.value.find(item => item.provider === form.provider)?.models || []), ...fetchedModels.value])])

function queryModelSuggestions(query: string, callback: (items: Array<{ value: string }>) => void) {
  const keyword = query.trim().toLowerCase()
  callback(modelOptions.value
    .filter(model => !keyword || model.toLowerCase().includes(keyword))
    .map(value => ({ value })))
}

async function loadConfigs() {
  loading.value = true
  try { configs.value = await llmConfigApi.list() } catch { configs.value = []; ElMessage.error('本地模型列表读取失败') } finally { loading.value = false }
}

async function loadPresets() {
  if (presets.value.length) return
  try {
    const result = await llmConfigApi.getPresets()
    presets.value = Array.isArray(result) ? result : Object.entries(result || {}).map(([provider, value]: [string, any]) => ({ provider, label: provider, base_url: value.base_url || '', models: value.models || [] }))
  } catch { presets.value = [] }
}

function resetForm() { fetchedModels.value = []; Object.assign(form, { config_name: '', provider: 'minimax', base_url: '', api_key: '', model: '', purpose: 'all', max_tokens: 4096, temperature: 0.7, is_default: false, codex_wire_api: 'responses' }) }
function onProviderChange() { fetchedModels.value = []; const preset = presets.value.find(item => item.provider === form.provider); if (preset) { form.base_url = preset.base_url; form.model = preset.models[0] || '' } }
async function openCreate() { editing.value = null; resetForm(); await loadPresets(); onProviderChange(); dialogVisible.value = true }
async function openEdit(config: LlmConfig) { editing.value = config; fetchedModels.value = []; await loadPresets(); Object.assign(form, { config_name: config.config_name, provider: config.provider === 'gpt' ? 'dolphin' : config.provider, base_url: config.base_url, api_key: '', model: config.model, purpose: config.purpose, max_tokens: config.max_tokens, temperature: config.temperature, is_default: config.is_default, codex_wire_api: config.codex_wire_api || 'responses' }); dialogVisible.value = true }

async function fetchModels() {
  if (!form.base_url.trim() || !form.api_key.trim()) { ElMessage.warning('请先填写 API 地址和 API Key'); return }
  fetchingModels.value = true
  try {
    const result = await llmConfigApi.fetchModels({ provider: form.provider, base_url: form.base_url, api_key: form.api_key })
    fetchedModels.value = Array.isArray(result.models) ? result.models : []
    if (!fetchedModels.value.length) { ElMessage.warning('/models 未返回可用模型'); return }
    if (!form.model || !fetchedModels.value.includes(form.model)) form.model = fetchedModels.value[0]
    ElMessage.success(`已获取 ${fetchedModels.value.length} 个模型`)
  } catch { ElMessage.error('从 /models 获取模型失败') } finally { fetchingModels.value = false }
}

async function save() {
  if (!form.config_name.trim() || !form.base_url.trim() || !form.model.trim() || (!editing.value && !form.api_key.trim())) { ElMessage.warning('请填写模型名称、API 地址、模型名和 API Key'); return }
  saving.value = true
  try {
    const { api_key, ...fields } = form
    const data = { ...fields, ...(api_key.trim() ? { api_key } : {}) }
    if (editing.value) await llmConfigApi.update(editing.value.id, data)
    else await llmConfigApi.create(data)
    dialogVisible.value = false; ElMessage.success(editing.value ? '本地模型已更新' : '本地模型已添加'); await loadConfigs()
  } catch { ElMessage.error('保存本地模型失败') } finally { saving.value = false }
}
async function testConfig(config: ModelWithState) { config._testing = true; try { const result = await llmConfigApi.test(config.id); result.ok || result.success ? ElMessage.success('连接成功') : ElMessage.error(result.error || result.message || '连接失败') } catch { ElMessage.error('连接测试失败') } finally { config._testing = false } }
async function toggleStatus(config: ModelWithState) { try { await llmConfigApi.updateStatus(config.id, config.status === 'active' ? 'inactive' : 'active'); await loadConfigs() } catch { ElMessage.error('更新模型状态失败') } }
async function setDefault(config: ModelWithState) { try { await llmConfigApi.setDefault(config.id); ElMessage.success('已设为默认模型'); await loadConfigs() } catch { ElMessage.error('设置默认模型失败') } }
async function deleteConfig(config: ModelWithState) { try { await ElMessageBox.confirm(`确定删除「${config.config_name}」吗？`, '删除本地模型', { type: 'warning' }); await llmConfigApi.delete(config.id); ElMessage.success('本地模型已删除'); await loadConfigs() } catch { /* user cancellation or request failure */ } }

onMounted(() => { void loadConfigs() })
</script>

<style scoped>
.local-model-settings { max-width: 700px; margin-top: 12px; }
.local-model-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 16px 0 12px; color: var(--text-3); font-size: 12px; }
.local-model-toolbar > div, .model-actions { display: flex; align-items: center; gap: 2px; flex-wrap: wrap; }
.local-model-empty { min-height: 220px; display: grid; place-items: center; align-content: center; gap: 8px; padding: 20px; border: 1px dashed var(--line); border-radius: 9px; color: var(--text-3); font-size: 12px; text-align: center; }
.local-model-empty strong { color: var(--text); font-size: 13px; }.local-model-empty :deep(.el-button) { margin-top: 8px; }
.local-model-list { overflow: hidden; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); }
.local-model-row { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; align-items: center; gap: 12px; min-height: 78px; padding: 12px 14px; border-bottom: 1px solid var(--line); }.local-model-row:last-child { border-bottom: 0; }
.model-status { width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); }.model-status.active { background: var(--success, #2e8b57); }.model-status.error { background: var(--danger); }
.model-main { min-width: 0; display: grid; gap: 5px; }.model-title { display: flex; align-items: center; gap: 7px; }.model-title strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.model-main > span { overflow: hidden; color: var(--text-3); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.form-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }.form-pair :deep(.el-select), .form-pair :deep(.el-input-number) { width: 100%; }
.form-tip { margin-top: 5px; color: var(--text-3); font-size: 12px; line-height: 1.5; }
.model-picker { display: flex; width: 100%; gap: 8px; }.model-picker :deep(.el-autocomplete) { min-width: 0; flex: 1; }.model-picker :deep(.el-autocomplete .el-input) { width: 100%; }.model-picker :deep(.el-button) { flex: none; }
.delete-action, .delete-action:hover, .delete-action:focus-visible { color: var(--text-2); border-color: var(--line); background: transparent; }
@media (max-width: 760px) { .local-model-toolbar, .local-model-row { align-items: flex-start; }.local-model-toolbar { display: grid; }.local-model-row { grid-template-columns: 8px minmax(0, 1fr); }.model-actions { grid-column: 2; }.form-pair { grid-template-columns: 1fr; gap: 0; } }
</style>

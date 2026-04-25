<template>
  <BuilderFrame :breadcrumbs="[{ label: '设置' }, { label: activeTab === 'envs' ? '平台环境' : '模型配置' }]">
    <template #actions>
      <button v-if="activeTab === 'envs'" class="new-btn" @click="openCreate">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        添加环境
      </button>
      <button v-if="activeTab === 'llm'" class="new-btn" @click="openLlmCreate">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新增模型
      </button>
    </template>
    <div class="envs-main builder-page">
      <div class="tabs-bar">
        <div class="tabs-group">
          <button :class="['tab-item', { active: activeTab === 'envs' }]" @click="setActiveTab('envs')">平台环境</button>
          <button :class="['tab-item', { active: activeTab === 'llm' }]" @click="setActiveTab('llm')">模型配置</button>
        </div>
        <div class="tabs-summary">
          {{ activeTab === 'envs' ? `${envs.length} 个环境连接` : `${llmConfigs.length} 个模型配置` }}
        </div>
      </div>

      <!-- ==================== Tab 1: 平台环境 ==================== -->
      <div v-show="activeTab === 'envs'" class="env-content">
      <div v-if="loading" class="empty-state">加载中...</div>
      <div v-else-if="envs.length === 0" class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.3"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        <span>暂无环境配置</span>
        <button class="empty-add-btn" @click="openCreate">添加第一个环境</button>
      </div>

      <template v-else>
        <div class="env-grid">
          <div v-for="env in envs" :key="env.id" class="env-card">
            <div class="env-card-header">
              <div class="env-card-left">
                <div class="env-status-dot" :class="env.status"></div>
                <h3 class="env-name">
                  {{ env.env_name }}
                  <span v-if="env.is_default" class="default-star">&#11088;</span>
                </h3>
              </div>
              <span class="env-status-tag" :class="env.status">
                {{ env.status === 'connected' ? '已连接' : '未连接' }}
              </span>
            </div>

            <div class="env-card-body">
              <div class="env-field">
                <span class="env-label">平台地址</span>
                <span class="env-value">{{ env.base_url }}</span>
              </div>
              <div class="env-field">
                <span class="env-label">租户ID</span>
                <span class="env-value mono">{{ env.platform_tenant_id }}</span>
              </div>
              <div class="env-field" v-if="env.username">
                <span class="env-label">用户名</span>
                <span class="env-value">{{ env.username }}</span>
              </div>
            </div>

            <div class="env-card-actions">
              <button class="env-action-btn" @click="handleTest(env)" :disabled="env._testing" title="测试连接">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                {{ env._testing ? '测试中...' : '测试' }}
              </button>
              <button class="env-action-btn" @click="handleLogin(env)" :disabled="env._logging" title="登录">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
                {{ env._logging ? '登录中...' : '登录' }}
              </button>
              <button v-if="!env.is_default" class="env-action-btn" @click="handleSetDefault(env)" title="设为默认">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                默认
              </button>
              <button class="env-action-btn" @click="openEdit(env)" title="编辑">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                编辑
              </button>
              <button class="env-action-btn danger" @click="handleDelete(env)" title="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                删除
              </button>
            </div>
          </div>
        </div>
      </template>
      </div>

      <!-- ==================== Tab 2: 模型配置 ==================== -->
      <div v-show="activeTab === 'llm'" class="env-content">
      <div v-if="llmLoading" class="empty-state">加载中...</div>
      <div v-else-if="llmConfigs.length === 0" class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.3"><path d="M12 2a4 4 0 0 0-4 4v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4z"/><circle cx="12" cy="15" r="2"/></svg>
        <span>暂无模型配置</span>
        <button class="empty-add-btn" @click="openLlmCreate">新增第一个模型</button>
      </div>

      <template v-else>
        <div class="env-grid">
          <div v-for="cfg in llmConfigs" :key="cfg.id" class="env-card">
            <div class="env-card-header">
              <div class="env-card-left">
                <div class="env-status-dot" :class="cfg.status === 'active' ? 'connected' : 'disconnected'"></div>
                <h3 class="env-name">
                  {{ cfg.config_name }}
                  <span v-if="cfg.is_default" class="default-star">&#11088;</span>
                </h3>
              </div>
              <span class="env-status-tag" :class="cfg.status === 'active' ? 'connected' : 'disconnected'">
                {{ cfg.status === 'active' ? '可用' : cfg.status === 'error' ? '异常' : '未启用' }}
              </span>
            </div>

            <div class="env-card-body">
              <div class="env-field">
                <span class="env-label">供应商</span>
                <span class="env-value">{{ providerLabel(cfg.provider) }}</span>
              </div>
              <div class="env-field">
                <span class="env-label">模型</span>
                <span class="env-value mono">{{ cfg.model }}</span>
              </div>
              <div class="env-field">
                <span class="env-label">用途</span>
                <span class="env-value">{{ purposeLabel(cfg.purpose) }}</span>
              </div>
              <div class="env-field">
                <span class="env-label">参数</span>
                <span class="env-value">max_tokens: {{ cfg.max_tokens }} / temperature: {{ cfg.temperature }}</span>
              </div>
            </div>

            <div class="env-card-actions">
              <button class="env-action-btn" @click="handleLlmTest(cfg)" :disabled="cfg._testing" title="测试连接">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                {{ cfg._testing ? '测试中...' : '测试' }}
              </button>
              <button
                class="env-action-btn status-toggle"
                :class="{ inactive: cfg.status === 'inactive' }"
                @click="handleLlmToggleStatus(cfg)"
                :disabled="cfg._toggling"
                :title="cfg.status === 'inactive' ? '启用模型' : '禁用模型'"
              >
                <svg v-if="cfg.status === 'inactive'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                {{ cfg._toggling ? (cfg.status === 'inactive' ? '启用中...' : '禁用中...') : (cfg.status === 'inactive' ? '启用' : '禁用') }}
              </button>
              <button v-if="!cfg.is_default && cfg.status === 'active'" class="env-action-btn" @click="handleLlmSetDefault(cfg)" title="设为默认">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                默认
              </button>
              <button class="env-action-btn" @click="openLlmEdit(cfg)" title="编辑">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                编辑
              </button>
              <button class="env-action-btn danger" @click="handleLlmDelete(cfg)" title="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                删除
              </button>
            </div>
          </div>
        </div>
      </template>
      </div>

      <!-- ==================== 平台环境 Dialog ==================== -->
      <el-dialog
      v-model="dialogVisible"
      :title="editingEnv ? '编辑环境' : '添加环境'"
      width="520px"
      :close-on-click-modal="false"
      class="env-dialog"
      :append-to-body="true"
    >
      <el-form :model="form" label-position="top" class="env-form">
        <el-form-item label="环境名称" required>
          <el-input v-model="form.env_name" placeholder="如：开发环境、测试环境" />
        </el-form-item>
        <el-form-item label="平台地址" required>
          <el-input v-model="form.base_url" placeholder="https://apaas.example.com/backend" />
        </el-form-item>
        <el-form-item label="租户ID" required>
          <el-input v-model="form.platform_tenant_id" placeholder="输入平台租户ID" />
        </el-form-item>

        <div class="auth-section">
          <div class="auth-section-label">认证方式</div>
          <div class="auth-tabs">
            <button
              :class="['auth-tab', { active: authMode === 'password' }]"
              @click="authMode = 'password'"
              type="button"
            >账号密码</button>
            <button
              :class="['auth-tab', { active: authMode === 'token' }]"
              @click="authMode = 'token'"
              type="button"
            >Token 直连</button>
          </div>

          <template v-if="authMode === 'password'">
            <el-form-item label="用户名">
              <el-input v-model="form.username" placeholder="平台登录用户名" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" show-password placeholder="平台登录密码" />
            </el-form-item>
          </template>
          <template v-else>
            <el-form-item label="Token">
              <el-input v-model="form.token" type="textarea" :rows="3" placeholder="粘贴平台 Token" />
            </el-form-item>
          </template>
        </div>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">
          {{ editingEnv ? '保存' : '添加' }}
        </el-button>
      </template>
      </el-dialog>

      <!-- ==================== 模型配置 Dialog ==================== -->
      <el-dialog
      v-model="llmDialogVisible"
      :title="editingLlm ? '编辑模型配置' : '新增模型配置'"
      width="560px"
      :close-on-click-modal="false"
      class="env-dialog"
      :append-to-body="true"
      >
      <el-form :model="llmForm" label-position="top" class="env-form">
        <el-form-item label="配置名称" required>
          <el-input v-model="llmForm.config_name" placeholder="如：MiniMax 主力模型" />
        </el-form-item>

        <el-form-item label="供应商" required>
          <el-select v-model="llmForm.provider" placeholder="选择供应商" style="width: 100%" @change="onProviderChange">
            <el-option v-for="p in providerOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>

        <el-form-item label="API 地址" required>
          <el-input v-model="llmForm.base_url" placeholder="https://api.example.com/v1" />
        </el-form-item>

        <el-form-item label="API Key" required>
          <el-input v-model="llmForm.api_key" type="password" show-password :placeholder="editingLlm ? '留空则不修改' : '输入 API Key'" />
        </el-form-item>

        <el-form-item label="模型" required>
          <el-select
            v-model="llmForm.model"
            filterable
            allow-create
            default-first-option
            placeholder="选择或输入模型名称"
            style="width: 100%"
          >
            <el-option v-for="m in currentModelOptions" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>

        <el-form-item label="用途">
          <el-select v-model="llmForm.purpose" style="width: 100%">
            <el-option label="全部场景" value="all" />
            <el-option label="应用构建" value="builder" />
            <el-option label="代码生成" value="coding" />
          </el-select>
        </el-form-item>

        <div class="llm-params-row">
          <el-form-item label="max_tokens" class="llm-param-item">
            <el-input-number v-model="llmForm.max_tokens" :min="256" :max="128000" :step="256" controls-position="right" style="width: 100%" />
          </el-form-item>
          <el-form-item label="temperature" class="llm-param-item">
            <div class="temperature-control">
              <el-slider v-model="llmForm.temperature" :min="0" :max="1" :step="0.1" :show-tooltip="true" style="flex:1" />
              <span class="temperature-value">{{ llmForm.temperature.toFixed(1) }}</span>
            </div>
          </el-form-item>
        </div>

        <el-form-item>
          <div class="llm-default-switch">
            <span class="llm-switch-label">设为默认模型</span>
            <el-switch v-model="llmForm.is_default" />
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="llmDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleLlmSave" :loading="llmSaving">
          {{ editingLlm ? '保存' : '添加' }}
        </el-button>
      </template>
      </el-dialog>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { handleError } from '@/utils/errorHandler'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'
import { llmConfigApi, type LlmConfig, type ProviderPreset } from '@/api/llmConfig'
import { providerOptions, providerLabel, purposeLabel } from '@/utils/llmConfig'
import BuilderFrame from '@/components/BuilderFrame.vue'

const route = useRoute()
const router = useRouter()

function normalizeTab(value: unknown): 'envs' | 'llm' {
  const raw = Array.isArray(value) ? value[0] : value
  return raw === 'llm' ? 'llm' : 'envs'
}

const activeTab = ref<'envs' | 'llm'>(normalizeTab(route.query.tab))

async function setActiveTab(tab: 'envs' | 'llm') {
  activeTab.value = tab
  router.replace({ path: '/platform-envs', query: { ...route.query, tab } })
  if (tab === 'llm') await loadLlmConfigs()
}

// ==================== 平台环境相关 ====================

interface EnvWithUI extends PlatformEnv {
  _testing?: boolean
  _logging?: boolean
}

const envs = ref<EnvWithUI[]>([])
const loading = ref(true)
const dialogVisible = ref(false)
const editingEnv = ref<PlatformEnv | null>(null)
const saving = ref(false)
const authMode = ref<'password' | 'token'>('password')

const form = reactive({
  env_name: '',
  base_url: '',
  platform_tenant_id: '',
  username: '',
  password: '',
  token: '',
})

function resetForm() {
  form.env_name = ''
  form.base_url = ''
  form.platform_tenant_id = ''
  form.username = ''
  form.password = ''
  form.token = ''
  authMode.value = 'password'
}

function openCreate() {
  editingEnv.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(env: PlatformEnv) {
  editingEnv.value = env
  form.env_name = env.env_name
  form.base_url = env.base_url
  form.platform_tenant_id = env.platform_tenant_id
  form.username = env.username || ''
  form.password = ''
  form.token = ''
  authMode.value = env.username ? 'password' : 'token'
  dialogVisible.value = true
}

async function loadEnvs() {
  try {
    const list = await platformEnvApi.list()
    envs.value = Array.isArray(list) ? list : []
  } catch {
    envs.value = []
  }
  loading.value = false
}

async function handleSave() {
  if (!form.env_name.trim() || !form.base_url.trim() || !form.platform_tenant_id.trim()) {
    ElMessage.warning('请填写必填字段')
    return
  }
  saving.value = true
  try {
    const data: any = {
      env_name: form.env_name,
      base_url: form.base_url,
      platform_tenant_id: form.platform_tenant_id,
    }
    if (authMode.value === 'password') {
      data.username = form.username
      if (form.password) data.password = form.password
    } else {
      if (form.token) data.token = form.token
    }

    if (editingEnv.value) {
      await platformEnvApi.update(editingEnv.value.id, data)
      ElMessage.success('已更新')
    } else {
      await platformEnvApi.create(data)
      ElMessage.success('已添加')
    }
    dialogVisible.value = false
    await loadEnvs()
  } catch (e: any) {
    handleError(e, { fallback: '操作失败' })
  }
  saving.value = false
}

async function handleTest(env: EnvWithUI) {
  env._testing = true
  try {
    const res = await platformEnvApi.test(env.id)
    if (res.ok) {
      ElMessage.success('连接成功')
      env.status = res.status
    } else {
      ElMessage.error(res.error || '连接失败')
    }
  } catch (e: any) {
    handleError(e, { fallback: '测试失败' })
  }
  env._testing = false
}

async function handleLogin(env: EnvWithUI) {
  env._logging = true
  try {
    const res = await platformEnvApi.login(env.id)
    if (res.ok) {
      ElMessage.success('登录成功')
      env.status = res.status
    } else {
      ElMessage.error('登录失败')
    }
  } catch (e: any) {
    handleError(e, { fallback: '登录失败' })
  }
  env._logging = false
}

async function handleSetDefault(env: PlatformEnv) {
  try {
    await platformEnvApi.setDefault(env.id)
    ElMessage.success(`已将「${env.env_name}」设为默认环境`)
    await loadEnvs()
  } catch (e: any) {
    handleError(e, { fallback: '设置失败' })
  }
}

async function handleDelete(env: PlatformEnv) {
  try {
    await ElMessageBox.confirm(`确定删除环境「${env.env_name}」？此操作不可恢复。`, '删除环境', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await platformEnvApi.delete(env.id)
    ElMessage.success('已删除')
    await loadEnvs()
  } catch { /* cancelled */ }
}

// ==================== LLM 模型配置相关 ====================

interface LlmConfigWithUI extends LlmConfig {
  _testing?: boolean
  _toggling?: boolean
}

const llmConfigs = ref<LlmConfigWithUI[]>([])
const llmLoading = ref(false)
const llmDialogVisible = ref(false)
const editingLlm = ref<LlmConfig | null>(null)
const llmSaving = ref(false)
const presets = ref<ProviderPreset[]>([])
const llmLoaded = ref(false)

const llmForm = reactive({
  config_name: '',
  provider: 'minimax',
  base_url: '',
  api_key: '',
  model: '',
  purpose: 'all',
  max_tokens: 4096,
  temperature: 0.7,
  is_default: false,
  status: 'active',
})

const currentModelOptions = computed(() => {
  const preset = presets.value.find(p => p.provider === llmForm.provider)
  return preset?.models || []
})

function resetLlmForm() {
  llmForm.config_name = ''
  llmForm.provider = 'minimax'
  llmForm.base_url = ''
  llmForm.api_key = ''
  llmForm.model = ''
  llmForm.purpose = 'all'
  llmForm.max_tokens = 4096
  llmForm.temperature = 0.7
  llmForm.is_default = false
  llmForm.status = 'active'
}

function onProviderChange(provider: string) {
  const preset = presets.value.find(p => p.provider === provider)
  if (preset) {
    llmForm.base_url = preset.base_url
    llmForm.model = preset.models[0] || ''
  } else {
    llmForm.base_url = ''
    llmForm.model = ''
  }
}

async function openLlmCreate() {
  editingLlm.value = null
  resetLlmForm()
  await loadPresets()
  onProviderChange(llmForm.provider)
  llmDialogVisible.value = true
}

function openLlmEdit(cfg: LlmConfig) {
  editingLlm.value = cfg
  llmForm.config_name = cfg.config_name
  llmForm.provider = cfg.provider
  llmForm.base_url = cfg.base_url
  llmForm.api_key = ''
  llmForm.model = cfg.model
  llmForm.purpose = cfg.purpose
  llmForm.max_tokens = cfg.max_tokens
  llmForm.temperature = cfg.temperature
  llmForm.is_default = cfg.is_default
  llmForm.status = cfg.status
  loadPresets()
  llmDialogVisible.value = true
}

async function loadPresets() {
  if (presets.value.length > 0) return
  try {
    const data = await llmConfigApi.getPresets()
    // Backend returns {minimax: {base_url, models}, ...} dict, convert to array
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      presets.value = Object.entries(data).map(([key, val]: [string, any]) => ({
        provider: key,
        label: key,
        base_url: val.base_url || '',
        models: val.models || [],
      }))
    } else {
      presets.value = Array.isArray(data) ? data : []
    }
  } catch {
    presets.value = []
  }
}

async function loadLlmConfigs() {
  if (llmLoaded.value) return
  llmLoading.value = true
  try {
    const list = await llmConfigApi.list()
    llmConfigs.value = Array.isArray(list) ? list : []
    llmLoaded.value = true
  } catch {
    llmConfigs.value = []
  }
  llmLoading.value = false
}

async function reloadLlmConfigs() {
  llmLoading.value = true
  try {
    const list = await llmConfigApi.list()
    llmConfigs.value = Array.isArray(list) ? list : []
  } catch {
    llmConfigs.value = []
  }
  llmLoading.value = false
}

async function handleLlmSave() {
  if (!llmForm.config_name.trim() || !llmForm.base_url.trim() || !llmForm.model.trim()) {
    ElMessage.warning('请填写必填字段')
    return
  }
  if (!editingLlm.value && !llmForm.api_key.trim()) {
    ElMessage.warning('请输入 API Key')
    return
  }
  llmSaving.value = true
  try {
    const data: any = {
      config_name: llmForm.config_name,
      provider: llmForm.provider,
      base_url: llmForm.base_url,
      model: llmForm.model,
      purpose: llmForm.purpose,
      max_tokens: llmForm.max_tokens,
      temperature: llmForm.temperature,
      is_default: llmForm.is_default,
      status: llmForm.status,
    }
    if (llmForm.api_key) {
      data.api_key = llmForm.api_key
    }

    if (editingLlm.value) {
      await llmConfigApi.update(editingLlm.value.id, data)
      ElMessage.success('已更新')
    } else {
      await llmConfigApi.create(data)
      ElMessage.success('已添加')
    }
    llmDialogVisible.value = false
    await reloadLlmConfigs()
  } catch (e: any) {
    handleError(e, { fallback: '操作失败' })
  }
  llmSaving.value = false
}

async function handleLlmTest(cfg: LlmConfigWithUI) {
  cfg._testing = true
  const previousStatus = cfg.status
  try {
    const res = await llmConfigApi.test(cfg.id)
    if (res.success) {
      ElMessage.success(res.reply ? `连接成功: ${res.reply}` : '连接成功')
      cfg.status = previousStatus === 'inactive' ? 'inactive' : 'active'
    } else {
      ElMessage.error(res.error || '连接失败')
      cfg.status = previousStatus === 'inactive' ? 'inactive' : 'error'
    }
  } catch (e: any) {
    handleError(e, { fallback: '测试失败' })
  }
  cfg._testing = false
}

async function handleLlmToggleStatus(cfg: LlmConfigWithUI) {
  const targetStatus = cfg.status === 'inactive' ? 'active' : 'inactive'
  const actionLabel = targetStatus === 'active' ? '启用' : '禁用'
  try {
    await ElMessageBox.confirm(
      `确定${actionLabel}模型「${cfg.config_name}」？${targetStatus === 'inactive' ? '禁用后将不会在任何场景下被选用。' : ''}`,
      `${actionLabel}模型`,
      {
        confirmButtonText: actionLabel,
        cancelButtonText: '取消',
        type: targetStatus === 'inactive' ? 'warning' : 'info',
      }
    )
    cfg._toggling = true
    await llmConfigApi.updateStatus(cfg.id, targetStatus as 'active' | 'inactive')
    ElMessage.success(`已${actionLabel}`)
    await reloadLlmConfigs()
  } catch (e: any) {
    if (e !== 'cancel' && e !== 'close') {
      handleError(e, { fallback: '${actionLabel}失败' })
    }
  } finally {
    cfg._toggling = false
  }
}

async function handleLlmSetDefault(cfg: LlmConfig) {
  try {
    await llmConfigApi.setDefault(cfg.id)
    ElMessage.success(`已将「${cfg.config_name}」设为默认模型`)
    await reloadLlmConfigs()
  } catch (e: any) {
    handleError(e, { fallback: '设置失败' })
  }
}

async function handleLlmDelete(cfg: LlmConfig) {
  try {
    await ElMessageBox.confirm(`确定删除模型配置「${cfg.config_name}」？此操作不可恢复。`, '删除模型配置', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await llmConfigApi.delete(cfg.id)
    ElMessage.success('已删除')
    await reloadLlmConfigs()
  } catch { /* cancelled */ }
}

// ==================== Lifecycle ====================

onMounted(() => {
  loadEnvs()
  if (activeTab.value === 'llm') loadLlmConfigs()
})

watch(
  () => route.query.tab,
  value => {
    const next = normalizeTab(value)
    activeTab.value = next
    if (next === 'llm') loadLlmConfigs()
  }
)
</script>

<style scoped>
.envs-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: var(--b-bg);
}

/* ── Nav ── */
.nav-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  background: var(--b-panel);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--b-line);
  flex-shrink: 0;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.back-btn {
  background: none;
  border: none;
  color: var(--b-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  transition: all 0.2s;
}
.back-btn:hover { color: var(--b-text); background: var(--b-bg-sub); }

.logo-box {
  width: 28px;
  height: 28px;
  background: var(--b-ink);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 700;
  font-size: 12px;
}

.title {
  font-size: 15px;
  font-weight: 600;
  color: var(--b-text);
}

.new-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  background: var(--b-ink);
  color: #fff;
  border: 1px solid var(--b-ink);
  padding: 0 12px;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.2s;
}
.nav-right-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.new-btn:hover { opacity: 0.9; }

:global(html[data-theme="dark"]) .new-btn,
:global(html[data-theme="dark"]) .empty-add-btn {
  background: var(--b-brand);
  border-color: var(--b-brand);
  color: #070a12;
}

/* ── Tabs Bar ── */
.tabs-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 1180px;
  margin: 0 auto 2px;
  width: 100%;
  padding: 0;
  background: transparent;
  border-bottom: none;
  flex-shrink: 0;
  box-sizing: border-box;
}

.tabs-group {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  padding: 3px;
  background: var(--b-panel);
  border: 1px solid var(--b-line);
  border-radius: 8px;
  box-shadow: var(--b-shadow-xs);
}

.tabs-summary {
  color: var(--b-text-muted);
  font-size: 12px;
  font-family: var(--b-mono);
}

.tab-item {
  height: 28px;
  padding: 0 12px;
  border: none;
  background: none;
  color: var(--b-text-muted);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  position: relative;
  border-radius: 6px;
  transition: all 0.2s;
}
.tab-item:hover {
  color: var(--b-text);
  background: var(--b-bg-sub);
}
.tab-item.active {
  color: var(--b-text);
  background: var(--b-bg-sub);
  box-shadow: inset 0 0 0 1px var(--b-line);
}

/* ── Content ── */
.env-content {
  flex: 1;
  overflow-y: auto;
  max-width: 1180px;
  margin: 0 auto;
  width: 100%;
  padding: 0 0 44px;
}

.empty-state {
  text-align: center;
  color: var(--b-text-muted);
  padding: 80px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}

.empty-add-btn {
  margin-top: 8px;
  background: var(--b-ink);
  color: #fff;
  border: 1px solid var(--b-ink);
  padding: 7px 14px;
  border-radius: 7px;
  font-size: 12px;
  cursor: pointer;
  transition: opacity 0.2s;
}
.empty-add-btn:hover { opacity: 0.9; }

/* ── Grid ── */
.env-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
}

/* ── Card ── */
.env-card {
  background: var(--b-panel);
  border: 1px solid var(--b-line);
  border-radius: 8px;
  padding: 14px;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: var(--b-shadow-xs);
}
.env-card:hover {
  border-color: var(--b-line-strong);
  box-shadow: var(--b-shadow-sm);
}

.env-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.env-card-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.env-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.env-status-dot.connected {
  background: #10b981;
}
.env-status-dot.disconnected {
  background: var(--b-text-faint);
}

.env-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--b-text);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.default-star {
  font-size: 14px;
}

.env-status-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 700;
}
.env-status-tag.connected {
  background: var(--b-teal-soft);
  color: var(--b-teal);
}
.env-status-tag.disconnected {
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
}

.env-card-body {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.env-field {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.env-label {
  font-size: 11px;
  color: var(--b-text-faint);
  flex-shrink: 0;
  min-width: 52px;
}

.env-value {
  font-size: 12px;
  color: var(--b-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-value.mono {
  font-family: var(--b-mono);
  font-size: 11px;
  color: var(--b-text-muted);
  background: var(--b-bg-sub);
  padding: 1px 6px;
  border-radius: 4px;
}

.env-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--b-line);
}

.env-action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--b-line);
  background: var(--b-panel-soft);
  color: var(--b-text-muted);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.env-action-btn:hover {
  background: var(--b-bg-sub);
  color: var(--b-text);
}
.env-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.env-action-btn.danger {
  border-color: rgba(209, 74, 97, 0.22);
  color: var(--b-red);
}
.env-action-btn.danger:hover {
  background: var(--b-red-soft);
  color: var(--b-red);
}
.env-action-btn.status-toggle {
  border-color: rgba(79, 110, 247, 0.22);
  color: var(--b-brand-ink);
}
.env-action-btn.status-toggle:hover {
  background: var(--b-brand-soft);
  color: var(--b-brand-ink);
}
.env-action-btn.status-toggle.inactive {
  border-color: rgba(15, 159, 143, 0.24);
  color: var(--b-teal);
}
.env-action-btn.status-toggle.inactive:hover {
  background: var(--b-teal-soft);
}

/* Dialog styles moved to non-scoped block below */

/* Auth section */
.auth-section {
  margin-top: 8px;
  padding: 16px;
  background: var(--b-bg-sub);
  border: 1px solid var(--b-line);
  border-radius: 8px;
}
.auth-section-label {
  font-size: 12px;
  color: var(--b-text-muted);
  margin-bottom: 10px;
  font-weight: 500;
}

/* Auth tabs */
.auth-tabs {
  display: flex;
  gap: 2px;
  background: var(--b-panel);
  border: 1px solid var(--b-line);
  border-radius: 8px;
  padding: 3px;
  margin: 8px 0 20px;
}

.auth-tab {
  flex: 1;
  padding: 8px 0;
  border: none;
  background: none;
  color: var(--b-text-muted);
  font-size: 13px;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s;
}
.auth-tab:hover {
  color: var(--b-text);
}
.auth-tab.active {
  background: var(--b-brand-soft);
  color: var(--b-brand-ink);
  font-weight: 600;
}

/* ── LLM Dialog extras ── */
.llm-params-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.llm-param-item {
  margin-bottom: 0;
}

.temperature-control {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.temperature-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--b-text);
  min-width: 28px;
  text-align: right;
  font-family: var(--b-mono);
}

.llm-default-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 0;
}

.llm-switch-label {
  font-size: 13px;
  color: var(--b-text-muted);
}

/* ── Scrollbar ── */
.env-content::-webkit-scrollbar {
  width: 6px;
}
.env-content::-webkit-scrollbar-track {
  background: transparent;
}
.env-content::-webkit-scrollbar-thumb {
  background: var(--b-line-strong);
  border-radius: 3px;
}
.env-content::-webkit-scrollbar-thumb:hover {
  background: var(--b-text-faint);
}
</style>

<style>
/* ── Dialog theme (non-scoped for teleported el-dialog) ── */
.el-dialog.env-dialog {
  background: var(--b-panel) !important;
  color: var(--b-text);
  border: 1px solid var(--b-line);
  border-radius: 8px;
}
.el-dialog.env-dialog .el-dialog__header {
  border-bottom: 1px solid var(--b-line);
  padding: 16px 20px;
}
.el-dialog.env-dialog .el-dialog__title {
  color: var(--b-text) !important;
  font-size: 15px;
  font-weight: 700;
}
.el-dialog.env-dialog .el-dialog__headerbtn .el-dialog__close {
  color: var(--b-text-muted);
}
.el-dialog.env-dialog .el-dialog__body {
  padding: 20px;
}
.el-dialog.env-dialog .el-dialog__footer {
  border-top: 1px solid var(--b-line);
  padding: 14px 20px;
}
.el-dialog.env-dialog .el-form-item__label {
  color: var(--b-text-muted) !important;
  font-size: 13px;
}
.el-dialog.env-dialog .el-input__wrapper {
  background: var(--b-panel-soft) !important;
  box-shadow: 0 0 0 1px var(--b-line) inset !important;
}
.el-dialog.env-dialog .el-input__inner {
  color: var(--b-text) !important;
  -webkit-text-fill-color: var(--b-text) !important;
}
.el-dialog.env-dialog .el-input__inner::placeholder {
  color: var(--b-text-faint) !important;
  -webkit-text-fill-color: var(--b-text-faint) !important;
}
.el-dialog.env-dialog .el-textarea__inner {
  background: var(--b-panel-soft) !important;
  box-shadow: 0 0 0 1px var(--b-line) inset !important;
  color: var(--b-text) !important;
}
.el-dialog.env-dialog .el-input__wrapper:hover,
.el-dialog.env-dialog .el-textarea__inner:hover {
  box-shadow: 0 0 0 1px var(--b-line-strong) inset !important;
}
.el-dialog.env-dialog .el-input__wrapper.is-focus,
.el-dialog.env-dialog .el-textarea__inner:focus {
  box-shadow: 0 0 0 1px var(--b-brand) inset !important;
}
.el-dialog.env-dialog .el-overlay {
  background-color: rgba(0, 0, 0, 0.6) !important;
}
/* 确保 dark 模式下 primary 按钮可见 + 字号统一 */
.el-dialog.env-dialog .el-button--primary {
  background: var(--b-brand) !important;
  border-color: var(--b-brand) !important;
  color: #ffffff !important;
}
.el-dialog.env-dialog .el-button--primary:hover,
.el-dialog.env-dialog .el-button--primary:focus {
  background: var(--b-brand-ink) !important;
  border-color: var(--b-brand-ink) !important;
  color: #ffffff !important;
}
.el-dialog.env-dialog .el-button {
  font-size: 14px;
  padding: 8px 18px;
}
/* 输入框字体放大（用户反馈过小） */
.el-dialog.env-dialog .el-input__inner,
.el-dialog.env-dialog .el-textarea__inner,
.el-dialog.env-dialog .el-select__wrapper {
  font-size: 14px !important;
}
.el-dialog.env-dialog .el-input,
.el-dialog.env-dialog .el-input-number {
  font-size: 14px;
}
.el-dialog.env-dialog .el-input__suffix {
  color: var(--b-text-muted);
}
/* 密码框眼睛图标 */
.el-dialog.env-dialog .el-input__password {
  color: var(--b-text-muted) !important;
}
.el-dialog.env-dialog .el-input__password:hover {
  color: var(--b-text) !important;
}
/* 确保 prefix/suffix icon 颜色 */
.el-dialog.env-dialog .el-input__prefix,
.el-dialog.env-dialog .el-input__suffix-inner {
  color: var(--b-text-muted) !important;
}
/* 覆盖浏览器自动填充的背景色 */
.el-dialog.env-dialog .el-input__inner:-webkit-autofill,
.el-dialog.env-dialog .el-input__inner:-webkit-autofill:hover,
.el-dialog.env-dialog .el-input__inner:-webkit-autofill:focus {
  -webkit-box-shadow: 0 0 0 1000px var(--b-panel-soft) inset !important;
  -webkit-text-fill-color: var(--b-text) !important;
  transition: background-color 5000s ease-in-out 0s;
}
/* 按钮样式覆盖（修：之前用了未定义的 --b-ink，dark 模式下变成默认浅色） */
.el-dialog.env-dialog .el-button--primary {
  background: var(--b-brand) !important;
  border: 1px solid var(--b-brand) !important;
  color: #ffffff !important;
}
.el-dialog.env-dialog .el-button--default {
  background: var(--b-panel-soft) !important;
  border: 1px solid var(--b-line) !important;
  color: var(--b-text-muted) !important;
}
.el-dialog.env-dialog .el-button--default:hover {
  background: var(--b-bg-sub) !important;
  color: var(--b-text) !important;
}
/* ── Select dropdown 主题 ── */
.el-dialog.env-dialog .el-select .el-input__wrapper {
  background: var(--b-panel-soft) !important;
  box-shadow: 0 0 0 1px var(--b-line) inset !important;
}
.el-dialog.env-dialog .el-select .el-input__inner {
  color: var(--b-text) !important;
  -webkit-text-fill-color: var(--b-text) !important;
}
/* ── InputNumber 主题 ── */
.el-dialog.env-dialog .el-input-number .el-input__wrapper {
  background: var(--b-panel-soft) !important;
  box-shadow: 0 0 0 1px var(--b-line) inset !important;
}
.el-dialog.env-dialog .el-input-number__decrease,
.el-dialog.env-dialog .el-input-number__increase {
  background: var(--b-bg-sub) !important;
  color: var(--b-text-muted) !important;
  border-color: var(--b-line) !important;
}
.el-dialog.env-dialog .el-input-number__decrease:hover,
.el-dialog.env-dialog .el-input-number__increase:hover {
  color: var(--b-text) !important;
}
/* ── Slider 主题 ── */
.el-dialog.env-dialog .el-slider__runway {
  background: var(--b-line) !important;
}
.el-dialog.env-dialog .el-slider__button {
  border-color: var(--b-brand) !important;
}
/* ── Switch 主题 ── */
.el-dialog.env-dialog .el-switch.is-checked .el-switch__core {
  border-color: var(--b-brand) !important;
  background-color: var(--b-brand) !important;
}
/* ── Select popper 全局样式 ── */
.el-select-dropdown {
  background: var(--b-panel) !important;
  border: 1px solid var(--b-line) !important;
}
.el-select-dropdown__item {
  color: var(--b-text-muted) !important;
}
.el-select-dropdown__item.hover,
.el-select-dropdown__item:hover {
  background: var(--b-bg-sub) !important;
  color: var(--b-text) !important;
}
.el-select-dropdown__item.is-selected {
  color: var(--b-brand-ink) !important;
  font-weight: 600;
}
.el-select-dropdown .el-scrollbar__bar {
  background: var(--b-line);
}
</style>

<template>
  <BuilderFrame :breadcrumbs="[{ label: '设置' }, { label: activeTabLabel }]">
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
          <button :class="['tab-item', { active: activeTab === 'assistant' }]" @click="setActiveTab('assistant')">得小帆</button>
        </div>
        <div class="tabs-summary">
          {{ tabSummary }}
        </div>
      </div>

      <!-- ==================== Tab 1: 平台环境 ==================== -->
      <div v-show="activeTab === 'envs'" class="env-content">
      <div v-if="loading" class="empty-state">
        <SkeletonCard :lines="3" with-footer />
      </div>
      <div v-else-if="envs.length === 0" class="empty-state">
        <EmptyState
          title="暂无环境配置"
          desc="添加一个 aPaaS 平台环境，登录后即可发布应用、同步元数据。"
        >
          <template #icon>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </template>
          <template #cta>
            <button class="empty-add-btn" @click="openCreate">添加第一个环境</button>
          </template>
        </EmptyState>
      </div>

      <template v-else>
        <div class="env-grid">
          <div v-for="env in envs" :key="env.id" class="env-card">
            <div class="env-card-header">
              <div class="env-card-left">
                <div class="env-status-dot" :class="env.status"></div>
                <h3 class="env-name">
                  {{ env.env_name }}
                  <span v-if="env.is_default" class="default-star"><AppIcon name="star" :size="12" /></span>
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
              <button class="env-action-btn danger" @click="handleDelete(env)" :disabled="env._deleting" title="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                {{ env._deleting ? '删除中...' : '删除' }}
              </button>
            </div>
          </div>
        </div>
      </template>
      </div>

      <!-- ==================== Tab 2: 模型配置 ==================== -->
      <div v-show="activeTab === 'llm'" class="env-content">
      <div v-if="llmLoading" class="empty-state">
        <SkeletonCard :lines="3" with-footer />
      </div>
      <div v-else-if="llmConfigs.length === 0" class="empty-state">
        <EmptyState
          title="暂无模型配置"
          desc="新增一个大模型配置，AI Builder / 二次开发 会自动消费这里的 API Key 与默认模型。"
        >
          <template #icon>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a4 4 0 0 0-4 4v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4z"/><circle cx="12" cy="15" r="2"/></svg>
          </template>
          <template #cta>
            <button class="empty-add-btn" @click="openLlmCreate">新增第一个模型</button>
          </template>
        </EmptyState>
      </div>

      <template v-else>
        <div class="env-grid">
          <div v-for="cfg in llmConfigs" :key="cfg.id" class="env-card">
            <div class="env-card-header">
              <div class="env-card-left">
                <div class="env-status-dot" :class="cfg.status === 'active' ? 'connected' : 'disconnected'"></div>
                <h3 class="env-name">
                  {{ cfg.config_name }}
                  <span v-if="cfg.is_default" class="default-star"><AppIcon name="star" :size="12" /></span>
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

      <!-- ==================== Tab 3: 得小帆 ==================== -->
      <div v-show="activeTab === 'assistant'" class="env-content">
        <div v-if="assistantLoading" class="empty-state">
          <SkeletonCard :lines="3" with-footer />
        </div>
        <div v-else class="assistant-settings-panel">
          <section class="assistant-settings-card">
            <div class="assistant-settings-head">
              <div>
                <h3>得小帆</h3>
                <p>配置 Dolphin 嵌入式得小帆，全局加载右下角浮窗。</p>
              </div>
              <el-switch
                v-model="assistantForm.enabled"
                active-text="启用"
                inactive-text="停用"
              />
            </div>

            <el-form label-position="top" class="env-form assistant-form">
              <el-form-item label="Dolphin 服务地址" required>
                <el-input v-model="assistantForm.server_url" placeholder="https://dolphin-trial.definesys.cn" />
              </el-form-item>
              <el-form-item label="Agent Code" required>
                <el-input v-model="assistantForm.agent_code" placeholder="填写得小帆发布后的 agent code" />
              </el-form-item>
              <el-form-item label="浮窗按钮文案">
                <el-input v-model="assistantForm.button_text" placeholder="得小帆" />
              </el-form-item>
            </el-form>

            <div class="assistant-settings-footer">
              <div class="assistant-status" :class="{ active: assistantForm.enabled && assistantForm.agent_code.trim() }">
                {{ assistantStatusText }}
              </div>
              <button class="new-btn" type="button" :disabled="assistantSaving" @click="saveAssistantSettings">
                {{ assistantSaving ? '保存中...' : '保存配置' }}
              </button>
            </div>
          </section>
        </div>
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
import { assistantSettingsApi } from '@/api/assistantSettings'
import { providerOptions, providerLabel, purposeLabel } from '@/utils/llmConfig'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import AppIcon from '@/components/common/AppIcon.vue'

const route = useRoute()
const router = useRouter()

type SettingsTab = 'envs' | 'llm' | 'assistant'

function normalizeTab(value: unknown): SettingsTab {
  const raw = Array.isArray(value) ? value[0] : value
  if (raw === 'assistant') return 'assistant'
  return raw === 'llm' ? 'llm' : 'envs'
}

const activeTab = ref<SettingsTab>(normalizeTab(route.query.tab))
const activeTabLabel = computed(() => {
  if (activeTab.value === 'envs') return '平台环境'
  if (activeTab.value === 'llm') return '模型配置'
  return '得小帆'
})

async function setActiveTab(tab: SettingsTab) {
  activeTab.value = tab
  router.replace({ path: '/platform-envs', query: { ...route.query, tab } })
  if (tab === 'llm') await loadLlmConfigs()
  if (tab === 'assistant') await loadAssistantSettings()
}

// ==================== 平台环境相关 ====================

interface EnvWithUI extends PlatformEnv {
  _testing?: boolean
  _logging?: boolean
  _deleting?: boolean
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
  } catch {
    return
  }

  const target = env as EnvWithUI
  target._deleting = true
  try {
    const res: any = await platformEnvApi.delete(env.id)
    const unlinked = Number(res?.unlinked_applications || 0)
    if (unlinked > 0) {
      ElMessage.success(`已删除，并解绑 ${unlinked} 个关联应用`)
    } else {
      ElMessage.success('已删除')
    }
    await loadEnvs()
  } catch (e: any) {
    handleError(e, { fallback: '删除失败' })
  } finally {
    target._deleting = false
  }
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
  llmForm.provider = cfg.provider === 'gpt' ? 'dolphin' : cfg.provider
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

// ==================== 得小帆配置 ====================

const assistantLoading = ref(false)
const assistantSaving = ref(false)
const assistantLoaded = ref(false)
const assistantForm = reactive({
  enabled: false,
  server_url: 'https://dolphin-trial.definesys.cn',
  agent_code: '',
  button_text: '得小帆',
})
const tabSummary = computed(() => {
  if (activeTab.value === 'envs') return `${envs.value.length} 个环境连接`
  if (activeTab.value === 'llm') return `${llmConfigs.value.length} 个模型配置`
  return assistantForm.enabled && assistantForm.agent_code.trim() ? '得小帆已启用' : '得小帆未启用'
})
const assistantStatusText = computed(() => {
  if (assistantForm.enabled && assistantForm.agent_code.trim()) return '已配置，刷新页面后会加载浮窗'
  if (assistantForm.enabled) return '已启用，但还缺 Agent Code'
  return '当前停用'
})

async function loadAssistantSettings() {
  if (assistantLoaded.value) return
  assistantLoading.value = true
  try {
    const data = await assistantSettingsApi.getDolphin()
    assistantForm.enabled = !!data.enabled
    assistantForm.server_url = data.server_url || 'https://dolphin-trial.definesys.cn'
    assistantForm.agent_code = data.agent_code || ''
    assistantForm.button_text = !data.button_text || data.button_text === '问题助手' ? '得小帆' : data.button_text
    assistantLoaded.value = true
  } catch (e: any) {
    handleError(e, { fallback: '加载得小帆配置失败' })
  } finally {
    assistantLoading.value = false
  }
}

async function saveAssistantSettings() {
  if (!assistantForm.server_url.trim()) {
    ElMessage.warning('请填写 Dolphin 服务地址')
    return
  }
  if (assistantForm.enabled && !assistantForm.agent_code.trim()) {
    ElMessage.warning('启用前请填写 Agent Code')
    return
  }
  assistantSaving.value = true
  try {
    const data = await assistantSettingsApi.saveDolphin({
      enabled: assistantForm.enabled,
      server_url: assistantForm.server_url,
      agent_code: assistantForm.agent_code,
      button_text: assistantForm.button_text || '得小帆',
    })
    assistantForm.enabled = !!data.enabled
    assistantForm.server_url = data.server_url
    assistantForm.agent_code = data.agent_code
    assistantForm.button_text = data.button_text
    assistantLoaded.value = true
    ElMessage.success('得小帆配置已保存，刷新页面后生效')
  } catch (e: any) {
    handleError(e, { fallback: '保存得小帆配置失败' })
  } finally {
    assistantSaving.value = false
  }
}

// ==================== Lifecycle ====================

onMounted(() => {
  loadEnvs()
  if (activeTab.value === 'llm') loadLlmConfigs()
  if (activeTab.value === 'assistant') loadAssistantSettings()
})

watch(
  () => route.query.tab,
  value => {
    const next = normalizeTab(value)
    activeTab.value = next
    if (next === 'llm') loadLlmConfigs()
    if (next === 'assistant') loadAssistantSettings()
  }
)
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Source: design-spec/07-admin.html §07.1 ENVIRONMENTS
   Preserved (don't change):
     - all class names referenced by template (.env-grid / .env-card /
       .env-card-header / .env-card-left / .env-status-dot / .env-name /
       .default-star / .env-status-tag / .env-card-body / .env-field /
       .env-label / .env-value / .env-card-actions / .env-action-btn /
       .auth-section / .auth-section-label / .auth-tabs / .auth-tab /
       .llm-params-row / .llm-param-item / .temperature-control /
       .temperature-value / .llm-default-switch / .llm-switch-label /
       .tabs-bar / .tabs-group / .tabs-summary / .tab-item /
       .env-content / .empty-state / .empty-add-btn / .new-btn)
     - dark theme overrides (re-scoped to v3 tokens — colors derive from
       v2→v3 alias block in design-v3-tokens.css)
     - dialog styles live in non-scoped <style> block (teleported el-dialog)
   Refreshed:
     - swap --b-* v2 vars → v3 tokens (--surface / --line / --text /
       --brand / --ok / --err / --warn / --r-* / --sh-* / --font-mono)
     - status dot 8×8 with 3px halo box-shadow (ok / surface-3 二色)
     - status tag rectangle r-1 (ok-soft / surface-3 二色 — not pill)
     - env-card border --line + r-4 + hover brand-ring + sh-2
     - card actions row gets top divider --line
     - action btn: neutral grey + hover brand-soft, .danger hover err-soft
     - "+ 添加环境/新增模型" topbar primary buttons go brand solid
     - tab switch underline 2px brand bottom (not pill)
     - default ★ marker forced text-rendered amber (#F59E0B) not emoji
     - auth-tab segmented: brand-soft active + transparent default
*/
.envs-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: transparent;
}

/* ── Topbar primary button (forwarded via BuilderFrame #actions slot) ── */
.new-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  background: var(--brand);
  color: #fff;
  border: 1px solid var(--brand);
  border-radius: var(--r-2, 6px);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: -0.005em;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.new-btn:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}
.new-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

/* ── Tabs bar (underline style, not pill) ── */
.tabs-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 1180px;
  margin: 0 auto;
  width: 100%;
  padding: 0 0 0 4px;
  background: transparent;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
  box-sizing: border-box;
}

.tabs-group {
  display: flex;
  align-items: center;
  gap: 0;
  min-width: 0;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
  box-shadow: none;
}

.tabs-summary {
  color: var(--text-3);
  font-size: 12px;
  font-family: var(--font-mono);
}

.tab-item {
  height: auto;
  padding: 10px 4px;
  margin-right: 18px;
  border: none;
  background: transparent;
  border-bottom: 2px solid transparent;
  color: var(--text-3);
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  position: relative;
  border-radius: 0;
  transition: color 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
  font-family: inherit;
}
.tab-item:hover {
  color: var(--text);
  background: transparent;
}
.tab-item.active {
  color: var(--text);
  background: transparent;
  border-bottom-color: var(--brand);
  font-weight: 600;
  box-shadow: none;
}

/* ── Content ── */
.env-content {
  flex: 1;
  overflow-y: auto;
  max-width: 1180px;
  margin: 0 auto;
  width: 100%;
  padding: 16px 0 44px;
}

.empty-state {
  text-align: center;
  color: var(--text-3);
  padding: 80px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}

.empty-add-btn {
  margin-top: 8px;
  background: var(--brand);
  color: #fff;
  border: 1px solid var(--brand);
  padding: 7px 14px;
  border-radius: var(--r-2, 6px);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.empty-add-btn:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

/* ── Grid ── */
.env-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

/* ── Card ── */
.env-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: 16px 18px 14px;
  transition: border-color 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
  display: flex;
  flex-direction: column;
  gap: 0;
}
.env-card:hover {
  border-color: var(--brand-ring);
  box-shadow: var(--sh-2);
}

.env-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
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
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-soft);
}
.env-status-dot.connected {
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-soft);
}
.env-status-dot.disconnected {
  background: var(--text-4);
  box-shadow: 0 0 0 3px var(--surface-3);
}

.env-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  letter-spacing: -0.005em;
}

/* Force the ⭐ emoji glyph (template uses &#11088;) to render as
   text-style amber star rather than full-color emoji. */
.default-star {
  color: #F59E0B;
  font-size: 12px;
  margin-left: 2px;
  font-variant-emoji: text;
  -webkit-font-feature-settings: 'liga' off;
}

.env-status-tag {
  font-size: 10.5px;
  padding: 2px 8px;
  border-radius: var(--r-1, 4px);
  font-weight: 600;
  letter-spacing: 0.02em;
  background: var(--ok-soft);
  color: var(--ok);
}
.env-status-tag.connected {
  background: var(--ok-soft);
  color: var(--ok);
}
.env-status-tag.disconnected {
  background: var(--surface-3);
  color: var(--text-3);
}

.env-card-body {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 6px 0;
}

.env-field {
  display: flex;
  align-items: baseline;
  gap: 12px;
  font-size: 12.5px;
  padding: 4px 0;
}

.env-label {
  font-size: 12.5px;
  color: var(--text-3);
  flex-shrink: 0;
  width: 60px;
  min-width: 60px;
}

.env-value {
  font-size: 12.5px;
  color: var(--text);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-value.mono {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text);
  background: transparent;
  padding: 0;
  border-radius: 0;
  font-weight: 500;
}

.env-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.env-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: var(--r-1, 4px);
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-2);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.env-action-btn:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}
.env-action-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}
.env-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.env-action-btn:disabled:hover {
  background: transparent;
  color: var(--text-2);
  border-color: var(--line);
}
.env-action-btn.danger {
  border-color: var(--line);
  color: var(--text-2);
}
.env-action-btn.danger:hover {
  background: var(--err-soft);
  color: var(--err);
  border-color: var(--err);
}
.env-action-btn.status-toggle {
  border-color: var(--line);
  color: var(--text-2);
}
.env-action-btn.status-toggle:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}
.env-action-btn.status-toggle.inactive {
  border-color: var(--line);
  color: var(--ok);
}
.env-action-btn.status-toggle.inactive:hover {
  background: var(--ok-soft);
  color: var(--ok);
  border-color: var(--ok);
}

/* Dialog styles moved to non-scoped block below */

/* Auth section */
.auth-section {
  margin-top: 8px;
  padding: 16px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
}
.auth-section-label {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 10px;
  font-weight: 500;
}

/* Auth tabs — segmented control (brand-soft active) */
.auth-tabs {
  display: flex;
  gap: 2px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  padding: 3px;
  margin: 8px 0 20px;
}

.auth-tab {
  flex: 1;
  padding: 8px 0;
  border: none;
  background: transparent;
  color: var(--text-3);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-radius: var(--r-2, 6px);
  font-family: inherit;
  transition: background 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.15s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.auth-tab:hover {
  color: var(--text);
}
.auth-tab.active {
  background: var(--brand-soft);
  color: var(--brand);
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
  color: var(--text);
  min-width: 28px;
  text-align: right;
  font-family: var(--font-mono);
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
  color: var(--text-2);
}

/* ── Assistant settings ── */
.assistant-settings-panel {
  max-width: 760px;
}
.assistant-settings-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: 18px;
  box-shadow: var(--sh-1);
}
.assistant-settings-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line);
}
.assistant-settings-head h3 {
  margin: 0 0 5px;
  color: var(--text);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0;
}
.assistant-settings-head p {
  margin: 0;
  color: var(--text-3);
  font-size: 12.5px;
  line-height: 1.6;
}
.assistant-form {
  padding-top: 16px;
}
.assistant-settings-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.assistant-status {
  min-height: 26px;
  display: inline-flex;
  align-items: center;
  padding: 0 9px;
  border-radius: var(--r-1, 4px);
  background: var(--surface-3);
  color: var(--text-3);
  font-size: 12px;
  font-weight: 650;
}
.assistant-status.active {
  background: var(--ok-soft);
  color: var(--ok);
}
.new-btn:disabled,
.new-btn:disabled:hover {
  opacity: 0.55;
  cursor: not-allowed;
  background: var(--brand);
  border-color: var(--brand);
}

/* ── Scrollbar ── */
.env-content::-webkit-scrollbar {
  width: 6px;
}
.env-content::-webkit-scrollbar-track {
  background: transparent;
}
.env-content::-webkit-scrollbar-thumb {
  background: var(--line-strong);
  border-radius: 3px;
}
.env-content::-webkit-scrollbar-thumb:hover {
  background: var(--text-4);
}

/* ── Dark theme overrides ── */
:global(html[data-theme="dark"]) .new-btn,
:global(html[data-theme="dark"]) .empty-add-btn {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-inverse);
}
:global(html[data-theme="dark"]) .new-btn:hover,
:global(html[data-theme="dark"]) .empty-add-btn:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: var(--text-inverse);
}

/* ── Phase 6 · table density + filter UX tightening (append-only) ──
   PlatformEnvs is a card grid (no el-table); only the tabs-bar is
   a "filter-like" surface. The Phase 4 underline-style tabs already
   match v3 spec, so this block only tightens the rhythm + adds a
   subtle hover-line on inactive tabs so they read as interactive. */

.tabs-bar {
  padding-top: 4px;
  padding-bottom: 0;
}
.tabs-summary {
  font-feature-settings: 'tnum';
  letter-spacing: 0.01em;
}

/* Inactive tab hover gets a 1px underline preview so it's clear they
   are clickable (Phase 4 only changes color on hover, which can be
   missed). 1px transparent → 1px text-4 on hover. */
.tab-item {
  border-bottom-width: 2px;
}
.tab-item:not(.active):hover {
  border-bottom-color: var(--line-strong);
}
</style>

<style>
/* v3 redesign · 2026-05-20 — el-dialog (teleported to body) styling.
   Lives outside scoped block because Element Plus dialog mounts to
   document.body and the .env-dialog class is the only handle we have.
   Token swap: --b-* (v2) → v3 tokens (--surface / --line / --text /
   --brand / --r-* / --font-mono). Logic untouched. */
html[data-theme="dark"] .builder-topbar .new-btn {
  background: var(--brand) !important;
  border-color: var(--brand) !important;
  color: var(--text-inverse) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .builder-topbar .new-btn:hover {
  background: var(--brand-hover) !important;
  border-color: var(--brand-hover) !important;
  color: var(--text-inverse) !important;
}

/* ── Dialog theme (non-scoped for teleported el-dialog) ── */
.el-dialog.env-dialog {
  background: var(--surface) !important;
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  box-shadow: var(--sh-4) !important;
}
.el-dialog.env-dialog .el-dialog__header {
  border-bottom: 1px solid var(--line);
  padding: 16px 20px;
}
.el-dialog.env-dialog .el-dialog__title {
  color: var(--text) !important;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.005em;
}
.el-dialog.env-dialog .el-dialog__headerbtn .el-dialog__close {
  color: var(--text-3);
}
.el-dialog.env-dialog .el-dialog__body {
  padding: 20px;
}
.el-dialog.env-dialog .el-dialog__footer {
  border-top: 1px solid var(--line);
  padding: 14px 20px;
}
.el-dialog.env-dialog .el-form-item__label {
  color: var(--text-2) !important;
  font-size: 13px;
}
.el-dialog.env-dialog .el-input__wrapper {
  background: var(--surface-2) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
}
.el-dialog.env-dialog .el-input__inner {
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
}
.el-dialog.env-dialog .el-input__inner::placeholder {
  color: var(--text-4) !important;
  -webkit-text-fill-color: var(--text-4) !important;
}
.el-dialog.env-dialog .el-textarea__inner {
  background: var(--surface-2) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
  color: var(--text) !important;
}
.el-dialog.env-dialog .el-input__wrapper:hover,
.el-dialog.env-dialog .el-textarea__inner:hover {
  box-shadow: 0 0 0 1px var(--line-strong) inset !important;
}
.el-dialog.env-dialog .el-input__wrapper.is-focus,
.el-dialog.env-dialog .el-textarea__inner:focus {
  box-shadow: 0 0 0 1px var(--brand) inset !important;
}
.el-dialog.env-dialog .el-overlay {
  background-color: rgba(11, 27, 63, 0.45) !important;
}
/* primary button — brand solid */
.el-dialog.env-dialog .el-button--primary {
  background: var(--brand) !important;
  border-color: var(--brand) !important;
  color: #ffffff !important;
}
.el-dialog.env-dialog .el-button--primary:hover,
.el-dialog.env-dialog .el-button--primary:focus {
  background: var(--brand-hover) !important;
  border-color: var(--brand-hover) !important;
  color: #ffffff !important;
}
.el-dialog.env-dialog .el-button {
  font-size: 14px;
  padding: 8px 18px;
  border-radius: var(--r-2, 6px);
}
/* input font-size lift (user requested) */
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
  color: var(--text-3);
}
/* password reveal icon */
.el-dialog.env-dialog .el-input__password {
  color: var(--text-3) !important;
}
.el-dialog.env-dialog .el-input__password:hover {
  color: var(--text) !important;
}
/* prefix/suffix icon color */
.el-dialog.env-dialog .el-input__prefix,
.el-dialog.env-dialog .el-input__suffix-inner {
  color: var(--text-3) !important;
}
/* override browser autofill background */
.el-dialog.env-dialog .el-input__inner:-webkit-autofill,
.el-dialog.env-dialog .el-input__inner:-webkit-autofill:hover,
.el-dialog.env-dialog .el-input__inner:-webkit-autofill:focus {
  -webkit-box-shadow: 0 0 0 1000px var(--surface-2) inset !important;
  -webkit-text-fill-color: var(--text) !important;
  transition: background-color 5000s ease-in-out 0s;
}
/* default (cancel) button — neutral */
.el-dialog.env-dialog .el-button--default {
  background: var(--surface-2) !important;
  border: 1px solid var(--line) !important;
  color: var(--text-2) !important;
}
.el-dialog.env-dialog .el-button--default:hover {
  background: var(--surface-3) !important;
  color: var(--text) !important;
  border-color: var(--line-strong) !important;
}
/* ── Select dropdown theme ── */
.el-dialog.env-dialog .el-select .el-input__wrapper {
  background: var(--surface-2) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
}
.el-dialog.env-dialog .el-select .el-input__inner {
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
}
/* ── InputNumber theme ── */
.el-dialog.env-dialog .el-input-number .el-input__wrapper {
  background: var(--surface-2) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
}
.el-dialog.env-dialog .el-input-number__decrease,
.el-dialog.env-dialog .el-input-number__increase {
  background: var(--surface-3) !important;
  color: var(--text-3) !important;
  border-color: var(--line) !important;
}
.el-dialog.env-dialog .el-input-number__decrease:hover,
.el-dialog.env-dialog .el-input-number__increase:hover {
  color: var(--text) !important;
}
/* ── Slider theme ── */
.el-dialog.env-dialog .el-slider__runway {
  background: var(--line) !important;
}
.el-dialog.env-dialog .el-slider__bar {
  background: var(--brand) !important;
}
.el-dialog.env-dialog .el-slider__button {
  border-color: var(--brand) !important;
}
/* ── Switch theme ── */
.el-dialog.env-dialog .el-switch.is-checked .el-switch__core {
  border-color: var(--brand) !important;
  background-color: var(--brand) !important;
}
/* ── Select popper (mounted to body) ── */
.el-select-dropdown {
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  border-radius: var(--r-3, 8px) !important;
  box-shadow: var(--sh-3) !important;
}
.el-select-dropdown__item {
  color: var(--text-2) !important;
}
.el-select-dropdown__item.hover,
.el-select-dropdown__item:hover {
  background: var(--surface-2) !important;
  color: var(--text) !important;
}
.el-select-dropdown__item.is-selected {
  color: var(--brand) !important;
  font-weight: 600;
}
.el-select-dropdown .el-scrollbar__bar {
  background: var(--line);
}
</style>

<template>
  <div class="envs-page">
    <nav class="nav-bar">
      <div class="nav-left">
        <button class="back-btn" @click="router.push('/')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
        <div class="logo-box">E</div>
        <span class="title">环境管理</span>
      </div>
      <button class="new-btn" @click="openCreate">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        添加环境
      </button>
    </nav>

    <div class="env-content">
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

    <!-- Add / Edit Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingEnv ? '编辑环境' : '添加环境'"
      width="520px"
      :close-on-click-modal="false"
      class="env-dialog"
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
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">
          {{ editingEnv ? '保存' : '添加' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'

const router = useRouter()

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
    ElMessage.error(e?.response?.data?.detail || '操作失败')
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
    ElMessage.error(e?.response?.data?.detail || '测试失败')
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
    ElMessage.error(e?.response?.data?.detail || '登录失败')
  }
  env._logging = false
}

async function handleSetDefault(env: PlatformEnv) {
  try {
    await platformEnvApi.setDefault(env.id)
    ElMessage.success(`已将「${env.env_name}」设为默认环境`)
    await loadEnvs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '设置失败')
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

onMounted(() => {
  loadEnvs()
})
</script>

<style scoped>
.envs-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #141418;
  color: rgba(255, 255, 255, 0.92);
}

/* ── Nav ── */
.nav-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  background: rgba(26, 26, 32, 0.82);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
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
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  transition: all 0.2s;
}
.back-btn:hover { color: #fff; background: rgba(255,255,255,0.06); }

.logo-box {
  width: 28px;
  height: 28px;
  background: linear-gradient(135deg, #7c3aed, #6366f1);
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
  color: rgba(255, 255, 255, 0.92);
}

.new-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  color: #fff;
  border: none;
  padding: 8px 18px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}
.new-btn:hover { opacity: 0.9; }

/* ── Content ── */
.env-content {
  flex: 1;
  overflow-y: auto;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  padding: 24px 24px 60px;
}

.empty-state {
  text-align: center;
  color: rgba(255, 255, 255, 0.35);
  padding: 80px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}

.empty-add-btn {
  margin-top: 8px;
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  color: #fff;
  border: none;
  padding: 8px 20px;
  border-radius: 10px;
  font-size: 13px;
  cursor: pointer;
  transition: opacity 0.2s;
}
.empty-add-btn:hover { opacity: 0.9; }

/* ── Grid ── */
.env-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

/* ── Card ── */
.env-card {
  background: #1e1e26;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 14px;
  padding: 20px;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.env-card:hover {
  background: #252530;
  border-color: rgba(124, 58, 237, 0.25);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.env-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.env-card-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.env-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.env-status-dot.connected {
  background: #34d399;
  box-shadow: 0 0 8px rgba(52, 211, 153, 0.4);
}
.env-status-dot.disconnected {
  background: rgba(255, 255, 255, 0.3);
}

.env-name {
  font-size: 15px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
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
  padding: 2px 10px;
  border-radius: 10px;
  font-weight: 500;
}
.env-status-tag.connected {
  background: rgba(52, 211, 153, 0.15);
  color: #34d399;
}
.env-status-tag.disconnected {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.4);
}

.env-card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.env-field {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.env-label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.35);
  flex-shrink: 0;
  min-width: 52px;
}

.env-value {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-value.mono {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.04);
  padding: 1px 6px;
  border-radius: 4px;
}

.env-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}

.env-action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.5);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.env-action-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.9);
}
.env-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.env-action-btn.danger {
  border-color: rgba(239, 68, 68, 0.15);
  color: rgba(239, 68, 68, 0.5);
}
.env-action-btn.danger:hover {
  background: rgba(239, 68, 68, 0.1);
  color: #f87171;
}

/* ── Dialog dark theme ── */
:deep(.env-dialog .el-dialog) {
  background: #1a1a2e;
  color: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
}
:deep(.env-dialog .el-dialog__header) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  padding: 16px 20px;
}
:deep(.env-dialog .el-dialog__title) {
  color: rgba(255, 255, 255, 0.92);
  font-size: 15px;
  font-weight: 600;
}
:deep(.env-dialog .el-dialog__headerbtn .el-dialog__close) {
  color: rgba(255, 255, 255, 0.4);
}
:deep(.env-dialog .el-dialog__body) {
  padding: 20px;
}
:deep(.env-dialog .el-dialog__footer) {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding: 14px 20px;
}
:deep(.env-dialog .el-form-item__label) {
  color: rgba(255, 255, 255, 0.7);
  font-size: 13px;
}
:deep(.env-dialog .el-input__wrapper) {
  background: #252530;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.08) inset;
}
:deep(.env-dialog .el-input__inner) {
  color: rgba(255, 255, 255, 0.9);
}
:deep(.env-dialog .el-textarea__inner) {
  background: #252530;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.08) inset;
  color: rgba(255, 255, 255, 0.9);
}
:deep(.env-dialog .el-input__wrapper:hover),
:deep(.env-dialog .el-textarea__inner:hover) {
  box-shadow: 0 0 0 1px rgba(124, 58, 237, 0.3) inset;
}
:deep(.env-dialog .el-input__wrapper.is-focus),
:deep(.env-dialog .el-textarea__inner:focus) {
  box-shadow: 0 0 0 1px rgba(124, 58, 237, 0.5) inset;
}

/* Auth tabs */
.auth-tabs {
  display: flex;
  gap: 2px;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 10px;
  padding: 3px;
  margin-bottom: 16px;
}

.auth-tab {
  flex: 1;
  padding: 7px 0;
  border: none;
  background: none;
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s;
}
.auth-tab:hover {
  color: rgba(255, 255, 255, 0.7);
}
.auth-tab.active {
  background: rgba(124, 58, 237, 0.2);
  color: #c4b5fd;
  font-weight: 600;
}

/* ── Scrollbar ── */
.env-content::-webkit-scrollbar {
  width: 6px;
}
.env-content::-webkit-scrollbar-track {
  background: transparent;
}
.env-content::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 3px;
}
.env-content::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}
</style>

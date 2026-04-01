<template>
  <div class="login-page">
    <!-- 左侧品牌区 -->
    <div class="brand-panel">
      <div class="brand-content">
        <div class="brand-logo">
          <div class="logo-mark">A</div>
          <span class="logo-text">aPaaS Builder AI</span>
        </div>
        <h1 class="brand-headline">企业级 AI 低代码搭建平台</h1>
        <p class="brand-sub">用对话驱动应用构建，让开发效率提升 10 倍</p>
        <ul class="feature-list">
          <li><span class="dot"></span>对话式应用搭建</li>
          <li><span class="dot"></span>AI 驱动组件开发</li>
          <li><span class="dot"></span>智能文档解析</li>
          <li><span class="dot"></span>一键部署到平台</li>
        </ul>
      </div>
      <div class="brand-footer">
        <span>&copy; {{ new Date().getFullYear() }} aPaaS Builder AI</span>
      </div>
    </div>

    <!-- 右侧登录区 -->
    <div class="form-panel">
      <div class="form-card">
        <h2 class="form-title">欢迎使用</h2>
        <p class="form-subtitle">登录或注册以开始使用 aPaaS Builder AI</p>

        <el-tabs v-model="activeTab" class="login-tabs">
          <el-tab-pane label="登录" name="login">
            <el-form :model="loginForm" :rules="loginRules" ref="loginFormRef" @submit.prevent="handleLogin">
              <el-form-item prop="username">
                <el-input
                  v-model="loginForm.username"
                  placeholder="请输入用户名"
                  size="large"
                  prefix-icon="User"
                  autocomplete="username"
                  clearable
                />
              </el-form-item>

              <el-form-item prop="password">
                <el-input
                  v-model="loginForm.password"
                  type="password"
                  placeholder="请输入密码"
                  size="large"
                  prefix-icon="Lock"
                  autocomplete="current-password"
                  show-password
                  @keyup.enter="handleLogin"
                />
              </el-form-item>

              <el-form-item>
                <el-button
                  type="primary"
                  size="large"
                  :loading="loginLoading"
                  @click="handleLogin"
                  class="submit-btn"
                >
                  登录
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="注册" name="register">
            <el-form :model="registerForm" :rules="registerRules" ref="registerFormRef" @submit.prevent="handleRegister">
              <el-form-item prop="username">
                <el-input
                  v-model="registerForm.username"
                  placeholder="请输入用户名"
                  size="large"
                  prefix-icon="User"
                  autocomplete="off"
                  clearable
                />
              </el-form-item>

              <el-form-item prop="password">
                <el-input
                  v-model="registerForm.password"
                  type="password"
                  placeholder="请输入密码（至少6位）"
                  size="large"
                  prefix-icon="Lock"
                  autocomplete="new-password"
                  show-password
                />
              </el-form-item>

              <el-form-item prop="confirmPassword">
                <el-input
                  v-model="registerForm.confirmPassword"
                  type="password"
                  placeholder="请确认密码"
                  size="large"
                  prefix-icon="Lock"
                  autocomplete="new-password"
                  show-password
                  @keyup.enter="handleRegister"
                />
              </el-form-item>

              <el-form-item>
                <el-button
                  type="primary"
                  size="large"
                  :loading="registerLoading"
                  @click="handleRegister"
                  class="submit-btn"
                >
                  注册
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { authApi } from '@/api/auth'

const router = useRouter()
const userStore = useUserStore()

const activeTab = ref('login')
const loginFormRef = ref<FormInstance>()
const registerFormRef = ref<FormInstance>()
const loginLoading = ref(false)
const registerLoading = ref(false)

const loginForm = reactive({
  username: '',
  password: ''
})

const registerForm = reactive({
  username: '',
  password: '',
  confirmPassword: ''
})

const validateConfirmPassword = (_rule: any, value: any, callback: any) => {
  if (value === '') {
    callback(new Error('请再次输入密码'))
  } else if (value !== registerForm.password) {
    callback(new Error('两次输入密码不一致'))
  } else {
    callback()
  }
}

const loginRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const registerRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 20, message: '用户名长度在 3 到 20 个字符', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少 6 个字符', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, validator: validateConfirmPassword, trigger: 'blur' }
  ]
}

const handleLogin = async () => {
  if (!loginFormRef.value) return

  await loginFormRef.value.validate(async (valid) => {
    if (!valid) return

    loginLoading.value = true
    try {
      const result = await userStore.login(loginForm.username, loginForm.password)

      if (result.requiresSelection) {
        // 多租户用户 — 跳转到租户选择页
        router.push({
          path: '/tenant-select',
          query: {
            token: result.selectionToken,
            tenants: JSON.stringify(result.tenants)
          }
        })
      } else {
        // 单租户用户 — 直接登录
        ElMessage.success('登录成功')
        router.push('/')
      }
    } catch (error: any) {
      const detail =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        error?.message ||
        '登录失败，请检查用户名和密码'
      ElMessage.error(detail)
    } finally {
      loginLoading.value = false
    }
  })
}

const handleRegister = async () => {
  if (!registerFormRef.value) return

  await registerFormRef.value.validate(async (valid) => {
    if (!valid) return

    registerLoading.value = true
    try {
      const res = await authApi.register({
        username: registerForm.username,
        password: registerForm.password
      })
      // 注册成功后自动登录
      userStore.setToken(res.access_token)
      await userStore.fetchUser()
      ElMessage.success('注册成功')
      router.push('/')
    } catch (error: any) {
      const detail =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        error?.message ||
        '注册失败'
      ElMessage.error(detail)
    } finally {
      registerLoading.value = false
    }
  })
}
</script>

<style scoped>
/* ── Page layout: left brand + right form ── */
.login-page {
  min-height: 100vh;
  display: flex;
}

/* ── Left brand panel ── */
.brand-panel {
  flex: 0 0 58%;
  background: var(--t-brand-gradient);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 48px 56px;
  position: relative;
  overflow: hidden;
}

.brand-panel::before {
  content: '';
  position: absolute;
  top: -120px;
  right: -120px;
  width: 360px;
  height: 360px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
}

.brand-panel::after {
  content: '';
  position: absolute;
  bottom: -80px;
  left: -80px;
  width: 260px;
  height: 260px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.04);
}

.brand-content {
  position: relative;
  z-index: 1;
  margin-top: 32px;
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 48px;
}

.logo-mark {
  width: 48px;
  height: 48px;
  background: rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(8px);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -1px;
  flex-shrink: 0;
}

.logo-text {
  font-size: 20px;
  font-weight: 700;
  color: #fff;
  letter-spacing: -0.3px;
}

.brand-headline {
  margin: 0 0 16px 0;
  font-size: 34px;
  font-weight: 700;
  color: #fff;
  line-height: 1.3;
  letter-spacing: -0.5px;
}

.brand-sub {
  margin: 0 0 48px 0;
  font-size: 16px;
  color: rgba(255, 255, 255, 0.75);
  line-height: 1.6;
}

.feature-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.feature-list li {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 15px;
  color: rgba(255, 255, 255, 0.9);
  font-weight: 500;
}

.feature-list .dot {
  width: 8px;
  height: 8px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 50%;
  flex-shrink: 0;
}

.brand-footer {
  position: relative;
  z-index: 1;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.4);
}

/* ── Right form panel ── */
.form-panel {
  flex: 1;
  background: var(--t-bg-main, #fff);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.form-card {
  width: 100%;
  max-width: 420px;
  padding: 0 20px;
}

.form-title {
  margin: 0 0 8px 0;
  font-size: 28px;
  font-weight: 700;
  color: var(--t-text-primary, #1a1a1a);
}

.form-subtitle {
  margin: 0 0 32px 0;
  font-size: 14px;
  color: var(--t-text-muted, #888);
}

/* ── Tabs ── */
.login-tabs {
  margin-top: 0;
}

.login-tabs :deep(.el-tabs__header) {
  margin-bottom: 24px;
}

.login-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.login-tabs :deep(.el-tabs__item) {
  font-size: 16px;
  font-weight: 500;
  color: var(--t-text-muted, #999);
  transition: color 0.2s;
}

.login-tabs :deep(.el-tabs__item:hover) {
  color: var(--t-text-secondary, #555);
}

.login-tabs :deep(.el-tabs__item.is-active) {
  color: var(--t-text-primary, #1a1a1a);
  font-weight: 600;
}

.login-tabs :deep(.el-tabs__active-bar) {
  background: var(--t-brand-gradient);
}

.login-tabs :deep(.el-tabs__nav-wrap::after) {
  background-color: var(--t-border-subtle, #e5e7eb);
}

/* ── Input fields ── */
:deep(.el-input__wrapper) {
  background: var(--t-bg-main, #fff) !important;
  border-radius: 10px;
  box-shadow: 0 0 0 1px var(--t-border-subtle, #d1d5db) inset;
  transition: all 0.25s;
}

/* ── 覆盖浏览器 autofill 灰色/蓝色背景 ── */
:deep(.el-input__inner:-webkit-autofill),
:deep(.el-input__inner:-webkit-autofill:hover),
:deep(.el-input__inner:-webkit-autofill:focus),
:deep(.el-input__inner:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 9999px var(--t-bg-main, #fff) inset !important;
  -webkit-text-fill-color: var(--t-text-primary, #1a1a1a) !important;
  transition: background-color 9999s ease-in-out 0s;
  caret-color: var(--t-text-primary, #1a1a1a);
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--t-text-muted, #9ca3af) inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px var(--t-brand) inset;
}

:deep(.el-input__inner) {
  color: var(--t-text-primary, #1a1a1a);
}

:deep(.el-input__inner::placeholder) {
  color: var(--t-text-muted, #9ca3af);
}

:deep(.el-input__prefix .el-icon) {
  color: var(--t-text-muted, #9ca3af);
}

:deep(.el-input__suffix .el-icon) {
  color: var(--t-text-muted, #9ca3af);
}

/* ── Form labels ── */
:deep(.el-form-item__label) {
  color: var(--t-text-secondary, #374151);
  font-weight: 500;
}

/* ── Form items ── */
:deep(.el-form-item) {
  margin-bottom: 20px;
}

:deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

:deep(.el-form-item__error) {
  color: var(--t-danger);
}

:deep(.el-tabs__header) {
  margin-bottom: 24px;
}

/* ── Submit button ── */
.submit-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  background: var(--t-brand-gradient);
  border: none;
  border-radius: 10px;
  color: #fff;
  transition: all 0.25s;
}

.submit-btn:hover,
.submit-btn:focus {
  background: var(--t-brand-gradient);
  transform: translateY(-1px);
  box-shadow: 0 6px 20px var(--t-brand-glow);
}

.submit-btn:active {
  transform: translateY(0);
  box-shadow: none;
}

/* ── Responsive: stack on small screens ── */
@media (max-width: 640px) {
  .login-page {
    flex-direction: column;
  }

  .brand-panel {
    flex: none;
    padding: 32px 28px;
    min-height: auto;
  }

  .brand-headline {
    font-size: 24px;
  }

  .brand-sub {
    margin-bottom: 24px;
  }

  .feature-list {
    gap: 12px;
  }

  .brand-footer {
    display: none;
  }

  .form-panel {
    padding: 24px;
  }

  .form-card {
    padding: 28px;
  }
}
</style>

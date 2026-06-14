<template>
  <div :class="['login-page', { 'theme-dark': themeStore.isDark }]">
    <button
      type="button"
      class="login-theme-toggle"
      :title="themeStore.isDark ? '切换到浅色模式' : '切换到夜间模式'"
      @click="themeStore.toggle()"
    >
      <el-icon>
        <Sunny v-if="themeStore.isDark" />
        <Moon v-else />
      </el-icon>
      <span>{{ themeStore.isDark ? '浅色' : '夜间' }}</span>
    </button>

    <main class="login-shell">
      <section class="brand-pane" aria-label="aPaaS Builder AI">
        <div class="deco-circle deco-one" aria-hidden="true"></div>
        <div class="deco-circle deco-two" aria-hidden="true"></div>
        <div class="deco-circle deco-three" aria-hidden="true"></div>

        <div class="branding-content">
          <div class="brand-logo">
            <div class="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none">
                <rect x="3" y="3" width="8" height="8" rx="2.2" fill="currentColor" />
                <rect x="13" y="3" width="8" height="8" rx="2.2" fill="currentColor" opacity=".58" />
                <rect x="3" y="13" width="8" height="8" rx="2.2" fill="currentColor" opacity=".58" />
                <rect x="13" y="13" width="8" height="8" rx="2.2" fill="currentColor" />
              </svg>
            </div>
            <div>
              <h1>睿鲸 AI</h1>
              <p>aPaaS Builder AI</p>
            </div>
          </div>

          <p class="brand-slogan">Build aPaaS Apps with AI</p>

          <div class="brand-features" aria-label="核心能力">
            <div class="feature-item">
              <span aria-hidden="true"></span>
              <strong>需求沉淀为设计文档</strong>
            </div>
            <div class="feature-item">
              <span aria-hidden="true"></span>
              <strong>表单、流程、权限协同配置</strong>
            </div>
            <div class="feature-item">
              <span aria-hidden="true"></span>
              <strong>自开发工作区联动</strong>
            </div>
            <div class="feature-item">
              <span aria-hidden="true"></span>
              <strong>应用生成与持续维护</strong>
            </div>
          </div>
        </div>
      </section>

      <section class="auth-pane" aria-label="登录 aPaaS Builder AI">
        <div class="login-card">
          <div class="login-header">
            <h2>欢迎使用</h2>
            <p>登录以进入 AI Builder 工作台</p>
          </div>

          <el-form
            :model="loginForm"
            :rules="loginRules"
            ref="loginFormRef"
            class="login-form"
            @submit.prevent="handleLogin"
          >
            <el-form-item prop="username" class="login-field-item">
              <el-input
                v-model="loginForm.username"
                placeholder="请输入 aPaaS 账号"
                size="large"
                :prefix-icon="User"
                autocomplete="username"
                clearable
              />
            </el-form-item>

            <el-form-item prop="password" class="login-field-item">
              <el-input
                v-model="loginForm.password"
                type="password"
                placeholder="请输入 aPaaS 密码"
                size="large"
                :prefix-icon="Lock"
                autocomplete="current-password"
                show-password
                @keyup.enter="handleLogin"
              />
            </el-form-item>

            <el-form-item class="login-submit-item">
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
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, Moon, Sunny, User } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()

const loginFormRef = ref<FormInstance>()
const loginLoading = ref(false)

const loginForm = reactive({
  username: '',
  password: ''
})

const loginRules: FormRules = {
  username: [{ required: true, message: '请输入 aPaaS 账号', trigger: ['blur', 'change'] }],
  password: [{ required: true, message: '请输入 aPaaS 密码', trigger: ['blur', 'change'] }]
}

function safeRedirectPath(raw: unknown): string {
  const value = Array.isArray(raw) ? raw[0] : raw
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text.startsWith('/') || text.startsWith('//')) return ''
  if (text.startsWith('/login') || text.startsWith('/tenant-select')) return ''
  return text
}

const handleLogin = async () => {
  if (!loginFormRef.value) return

  await loginFormRef.value.validate(async (valid) => {
    if (!valid) return

    loginLoading.value = true
    try {
      const result = await userStore.login(loginForm.username, loginForm.password)

      if (result.requiresSelection) {
        const redirect = safeRedirectPath(route.query.redirect)
        router.push({
          path: '/tenant-select',
          query: {
            token: result.selectionToken,
            tenants: JSON.stringify(result.tenants),
            ...(redirect ? { redirect } : {})
          }
        })
      } else {
        ElMessage.success('登录成功')
        router.replace(safeRedirectPath(route.query.redirect) || '/')
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
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  overflow: hidden;
  background: #fff;
  color: #101828;
}

.login-theme-toggle {
  position: fixed;
  top: 22px;
  right: 26px;
  z-index: 5;
  height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: rgba(255, 255, 255, 0.9);
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(16px);
  cursor: pointer;
}

.login-theme-toggle:hover {
  background: #fff;
  color: #1d4ed8;
  border-color: rgba(37, 99, 235, 0.28);
}

.login-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1fr) clamp(520px, 36vw, 704px);
  align-items: stretch;
}

.brand-pane {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 72px 64px;
  color: #fff;
  background:
    radial-gradient(circle at 28% 18%, rgba(255, 255, 255, 0.16), transparent 28%),
    linear-gradient(135deg, #312e81 0%, #4338ca 48%, #6366f1 100%);
}

.deco-circle {
  position: absolute;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.035);
  pointer-events: none;
}

.deco-one {
  width: 360px;
  height: 360px;
  left: -110px;
  bottom: -120px;
}

.deco-two {
  width: 320px;
  height: 320px;
  right: 8%;
  top: -130px;
}

.deco-three {
  width: 210px;
  height: 210px;
  right: 16%;
  bottom: 17%;
}

.branding-content {
  position: relative;
  z-index: 1;
  width: min(420px, 100%);
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 20px;
}

.brand-mark {
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 16px;
  color: #dbeafe;
  background: rgba(255, 255, 255, 0.16);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.18);
}

.brand-mark svg {
  width: 30px;
  height: 30px;
}

.brand-logo h1 {
  margin: 0;
  color: #fff;
  font-size: 44px;
  line-height: 1.08;
  font-weight: 800;
  letter-spacing: 0;
}

.brand-logo p {
  margin: 7px 0 0;
  color: rgba(255, 255, 255, 0.72);
  font-size: 15px;
  font-weight: 600;
}

.brand-slogan {
  margin: 34px 0 0;
  color: rgba(255, 255, 255, 0.72);
  font-size: 20px;
  line-height: 1.5;
  font-weight: 500;
}

.brand-features {
  margin-top: 58px;
  display: grid;
  gap: 24px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 24px;
  color: rgba(255, 255, 255, 0.86);
}

.feature-item span {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.62);
}

.feature-item strong {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.4;
}

.auth-pane {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 72px 70px;
  background: #fff;
}

.login-card {
  width: min(380px, 100%);
}

.login-header {
  margin-bottom: 42px;
}

.login-header h2 {
  margin: 0;
  color: #111827;
  font-size: 34px;
  line-height: 1.2;
  font-weight: 800;
  letter-spacing: 0;
}

.login-header p {
  margin: 12px 0 0;
  color: #64748b;
  font-size: 15px;
  line-height: 1.6;
}

.login-form {
  margin: 0;
}

:deep(.el-form-item) {
  margin-bottom: 18px;
}

:deep(.login-field-item .el-form-item__content) {
  min-height: 52px;
  align-items: flex-start;
}

:deep(.login-field-item .el-form-item__error) {
  position: static;
  width: 100%;
  min-height: 16px;
  margin-top: 6px;
  line-height: 16px;
}

:deep(.el-input__wrapper) {
  height: 52px;
  padding: 0 16px;
  border-radius: 8px;
  background: #f8fafc !important;
  box-shadow: 0 0 0 1px #e2e8f0 inset !important;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #cbd5e1 inset !important;
}

:deep(.el-input__wrapper.is-focus) {
  background: #fff !important;
  box-shadow: 0 0 0 2px #4f46e5 inset !important;
}

:deep(.el-input__inner) {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
  caret-color: #4f46e5 !important;
  font-size: 15px;
  font-weight: 500;
}

:deep(.el-input__inner::placeholder) {
  color: #94a3b8 !important;
}

:deep(.el-input__prefix .el-icon),
:deep(.el-input__suffix .el-icon) {
  color: #94a3b8;
}

:deep(.el-input__inner:-webkit-autofill),
:deep(.el-input__inner:-webkit-autofill:hover),
:deep(.el-input__inner:-webkit-autofill:focus),
:deep(.el-input__inner:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 9999px #f8fafc inset !important;
  -webkit-text-fill-color: #111827 !important;
  caret-color: #4f46e5;
  transition: background-color 9999s ease-in-out 0s;
}

.login-submit-item {
  margin-top: 12px;
  margin-bottom: 0;
}

.submit-btn {
  width: 100%;
  height: 50px;
  border: 0;
  border-radius: 8px;
  color: #fff;
  background: #4f46e5 !important;
  border-color: #4f46e5 !important;
  font-size: 15px;
  font-weight: 700;
  box-shadow: none;
}

.submit-btn:hover,
.submit-btn:focus {
  color: #fff;
  background: #4338ca !important;
  border-color: #4338ca !important;
}

.submit-btn:focus-visible {
  outline: 2px solid rgba(79, 70, 229, 0.28);
  outline-offset: 3px;
}

.login-page.theme-dark {
  background: #0f172a;
  color: #f8fafc;
}

.login-page.theme-dark .brand-pane {
  background:
    radial-gradient(circle at 28% 18%, rgba(96, 165, 250, 0.18), transparent 28%),
    linear-gradient(135deg, #0f172a 0%, #1e1b4b 52%, #312e81 100%);
}

.login-page.theme-dark .auth-pane {
  background: #1e293b;
}

.login-page.theme-dark .login-theme-toggle {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(15, 23, 42, 0.86);
  color: #e2e8f0;
}

.login-page.theme-dark .login-header h2 {
  color: #f8fafc;
}

.login-page.theme-dark .login-header p {
  color: #94a3b8;
}

.login-page.theme-dark :deep(.el-input__wrapper) {
  background: #111827 !important;
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.2) inset !important;
}

.login-page.theme-dark :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.34) inset !important;
}

.login-page.theme-dark :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px #818cf8 inset !important;
}

.login-page.theme-dark :deep(.el-input__inner) {
  color: #f8fafc !important;
  -webkit-text-fill-color: #f8fafc !important;
  caret-color: #818cf8 !important;
}

.login-page.theme-dark :deep(.el-input__inner::placeholder) {
  color: #64748b !important;
}

.login-page.theme-dark :deep(.el-input__inner:-webkit-autofill),
.login-page.theme-dark :deep(.el-input__inner:-webkit-autofill:hover),
.login-page.theme-dark :deep(.el-input__inner:-webkit-autofill:focus),
.login-page.theme-dark :deep(.el-input__inner:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 9999px #111827 inset !important;
  -webkit-text-fill-color: #f8fafc !important;
}

.login-page.theme-dark .submit-btn {
  background: #6366f1 !important;
  border-color: #6366f1 !important;
}

.login-page.theme-dark .submit-btn:hover,
.login-page.theme-dark .submit-btn:focus {
  background: #818cf8 !important;
  border-color: #818cf8 !important;
  color: #0f172a;
}

@media (max-width: 980px) {
  .login-page {
    overflow: auto;
  }

  .login-shell {
    grid-template-columns: 1fr;
  }

  .brand-pane {
    min-height: 390px;
    padding: 88px 32px 48px;
  }

  .branding-content {
    width: min(520px, 100%);
  }

  .brand-features {
    margin-top: 36px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 18px 24px;
  }

  .auth-pane {
    min-height: calc(100vh - 390px);
    padding: 48px 32px 64px;
  }

  .login-card {
    width: min(380px, 100%);
  }
}

@media (max-width: 620px) {
  .login-theme-toggle {
    top: 14px;
    right: 14px;
  }

  .brand-pane {
    min-height: 310px;
    padding: 72px 24px 34px;
  }

  .brand-logo {
    gap: 14px;
  }

  .brand-mark {
    width: 48px;
    height: 48px;
    border-radius: 14px;
  }

  .brand-logo h1 {
    font-size: 32px;
  }

  .brand-logo p {
    font-size: 13px;
  }

  .brand-slogan {
    margin-top: 22px;
    font-size: 16px;
  }

  .brand-features {
    margin-top: 26px;
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .feature-item strong {
    font-size: 14px;
  }

  .deco-one {
    width: 260px;
    height: 260px;
  }

  .deco-two,
  .deco-three {
    display: none;
  }

  .auth-pane {
    min-height: auto;
    padding: 40px 24px 56px;
  }

  .login-card {
    width: 100%;
  }

  .login-header {
    margin-bottom: 30px;
  }

  .login-header h2 {
    font-size: 28px;
  }
}
</style>

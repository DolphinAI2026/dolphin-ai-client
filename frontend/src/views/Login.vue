<template>
  <div class="login-page">
    <div class="login-bg"></div>
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
      <section class="login-card" aria-label="登录睿鲸AI">
        <div class="login-brand">
          <div class="logo-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="8" height="8" rx="2" fill="currentColor" />
              <rect x="13" y="3" width="8" height="8" rx="2" fill="currentColor" opacity=".62" />
              <rect x="3" y="13" width="8" height="8" rx="2" fill="currentColor" opacity=".62" />
              <rect x="13" y="13" width="8" height="8" rx="2" fill="currentColor" />
            </svg>
          </div>
          <h1 class="login-title">睿鲸AI</h1>
          <p class="login-subtitle">请使用 aPaaS 账号和密码登录</p>
        </div>

        <div class="login-hint">
          登录后会自动识别你的 aPaaS 租户和平台管理权限。
        </div>

        <el-form
          :model="loginForm"
          :rules="loginRules"
          ref="loginFormRef"
          class="login-form"
          @submit.prevent="handleLogin"
        >
          <label class="login-label">aPaaS 账号</label>
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

          <label class="login-label">aPaaS 密码</label>
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

          <div class="login-row">
            <label class="remember-check"><input type="checkbox" checked> 记住登录状态</label>
            <button class="login-link" type="button">忘记密码？</button>
          </div>

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

        <p class="account-note">还没有账号？请联系平台管理员开通。</p>
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
        // 多租户用户 — 跳转到租户选择页
        router.push({
          path: '/tenant-select',
          query: {
            token: result.selectionToken,
            tenants: JSON.stringify(result.tenants),
            ...(redirect ? { redirect } : {})
          }
        })
      } else {
        // 单租户用户 — 直接登录
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
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  /* v3 redesign 2026-05-20: token-driven backgrounds + brand polish */
  background: linear-gradient(180deg, #F8FAFC 0%, var(--brand-soft, #EFF6FF) 100%);
  color: var(--text, #0B1B3F);
}

.login-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 760px 360px at 50% 26%, var(--brand-ring, rgba(29, 78, 216, 0.16)), transparent 68%),
    radial-gradient(ellipse 620px 300px at 50% 70%, var(--brand-glow, rgba(29, 78, 216, 0.12)), transparent 70%);
}

.login-theme-toggle {
  position: fixed;
  top: 18px;
  right: 20px;
  z-index: 5;
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border-radius: var(--r-2, 6px);
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  backdrop-filter: blur(16px);
  transition: all 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.login-theme-toggle:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}

.login-shell {
  position: relative;
  z-index: 1;
  width: min(560px, calc(100vw - 40px));
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  padding: 32px 0;
}

.logo-mark {
  width: 56px;
  height: 56px;
  margin: 0 auto 16px;
  border-radius: var(--r-4, 12px);
  display: grid;
  place-items: center;
  color: var(--text-inverse, #fff);
  background: linear-gradient(135deg, var(--blue-500, #3B82F6), var(--blue-800, #1E40AF));
  box-shadow: 0 14px 30px -10px var(--brand-glow, rgba(29, 78, 216, 0.32));
}

.logo-mark svg {
  width: 28px;
  height: 28px;
}

.login-card {
  width: min(520px, 100%);
  padding: 40px 42px;
  border-radius: var(--r-5, 16px);
  border: 1px solid var(--line);
  background: var(--surface);
  box-shadow: var(--sh-5, 0 24px 60px rgba(11, 27, 63, 0.14));
  backdrop-filter: blur(18px);
}

.login-brand {
  text-align: center;
  margin-bottom: 18px;
}

.login-title {
  margin: 0;
  color: var(--text);
  font-size: var(--t-h1, 32px);
  line-height: 1.2;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.02em;
}

.login-subtitle {
  margin: 10px 0 0;
  color: var(--text-3);
  font-size: 15px;
  line-height: 1.4;
}

.login-hint {
  margin: 0 0 24px;
  padding: 12px 14px;
  border: 1px solid var(--brand-ring);
  border-radius: var(--r-3, 8px);
  background: var(--brand-soft);
  color: var(--brand-text);
  font-size: 13.5px;
  line-height: 1.5;
  text-align: center;
}

.login-form {
  margin: 0;
}

.login-label {
  display: block;
  margin: 16px 0 8px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  letter-spacing: -0.005em;
}

:deep(.el-form-item) {
  margin-bottom: 0;
}

:deep(.login-field-item .el-form-item__content) {
  align-items: flex-start;
  min-height: 70px;
}

:deep(.login-field-item .el-form-item__error) {
  position: static;
  flex-basis: 100%;
  min-height: 16px;
  margin-top: 5px;
  padding-top: 0;
  line-height: 16px;
}

:deep(.el-input__wrapper) {
  height: 48px;
  padding: 0 14px;
  border-radius: var(--r-3, 8px);
  background: var(--surface) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
  transition: box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand-ring) inset !important;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px var(--brand) inset !important;
}

:deep(.el-input__inner) {
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  caret-color: var(--brand) !important;
  font-size: 14px;
  font-weight: 500;
}

:deep(.el-input__inner::placeholder) {
  color: var(--text-4) !important;
}

:deep(.el-input__prefix .el-icon),
:deep(.el-input__suffix .el-icon) {
  color: var(--text-3);
}

:deep(.el-input__inner:-webkit-autofill),
:deep(.el-input__inner:-webkit-autofill:hover),
:deep(.el-input__inner:-webkit-autofill:focus),
:deep(.el-input__inner:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 9999px var(--surface) inset !important;
  -webkit-text-fill-color: var(--text) !important;
  caret-color: var(--brand);
  transition: background-color 9999s ease-in-out 0s;
}

.login-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 14px 0 22px;
}

.remember-check {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
}

.remember-check input {
  accent-color: var(--brand);
}

.login-link {
  border: 0;
  background: transparent;
  color: var(--brand);
  font: inherit;
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
  transition: color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.login-link:hover {
  color: var(--brand-hover);
  text-decoration: underline;
}

.submit-btn {
  width: 100%;
  height: 48px;
  border: 0;
  border-radius: var(--r-3, 8px);
  color: var(--text-inverse, #fff);
  background: var(--brand);
  font-size: 15px;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: -0.005em;
  box-shadow: var(--sh-brand, 0 8px 22px -8px rgba(29, 78, 216, 0.32));
  cursor: pointer;
  transition: all 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.submit-btn:hover,
.submit-btn:focus {
  color: var(--text-inverse, #fff);
  background: var(--brand-hover);
  transform: translateY(-0.5px);
}

.submit-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 3px;
}

.account-note {
  margin: 20px 0 0;
  color: var(--text-3);
  text-align: center;
  font-size: 12.5px;
  line-height: 1.5;
}

:global(html[data-theme="dark"]) .login-theme-toggle {
  border-color: var(--line);
  background: var(--surface);
  color: var(--text-2);
}

:global(html[data-theme="dark"]) .login-page {
  background: linear-gradient(180deg, #0B1224 0%, #0A1020 100%);
  color: var(--text);
}

:global(html[data-theme="dark"]) .login-card {
  border-color: var(--line);
  background: var(--surface);
}

:global(html[data-theme="dark"]) .login-title {
  color: var(--text);
}

:global(html[data-theme="dark"]) .login-subtitle,
:global(html[data-theme="dark"]) .account-note {
  color: var(--text-3);
}

:global(html[data-theme="dark"]) .login-hint {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  color: var(--brand-text);
}

:global(html[data-theme="dark"]) :deep(.el-input__wrapper) {
  background: var(--surface-2) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
}

:global(html[data-theme="dark"]) :deep(.el-input__inner) {
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
}

@media (max-width: 780px) {
  .login-page {
    overflow: auto;
  }

  .login-shell {
    width: min(520px, calc(100vw - 28px));
    padding: 72px 0 24px;
  }

  .login-card {
    padding: 32px 24px;
  }
}
</style>

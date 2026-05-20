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
          <el-form-item prop="username">
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
          <el-form-item prop="password">
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
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, Moon, Sunny, User } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'

const router = useRouter()
const userStore = useUserStore()
const themeStore = useThemeStore()

const loginFormRef = ref<FormInstance>()
const loginLoading = ref(false)

const loginForm = reactive({
  username: '',
  password: ''
})

const loginRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
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
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(180deg, #fbfdff 0%, #f5f1ff 100%);
  color: #17162f;
}

.login-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 760px 360px at 50% 26%, rgba(101, 82, 220, 0.13), transparent 68%),
    radial-gradient(ellipse 620px 300px at 50% 70%, rgba(120, 108, 240, 0.11), transparent 70%);
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
  border-radius: 8px;
  border: 1px solid rgba(99, 91, 158, 0.14);
  background: rgba(255, 255, 255, 0.72);
  color: #625d82;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  backdrop-filter: blur(16px);
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
  border-radius: 14px;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(180deg, #786cf0, #5146c9);
  box-shadow: 0 14px 30px rgba(81, 70, 201, 0.26);
}

.logo-mark svg {
  width: 28px;
  height: 28px;
}

.login-card {
  width: min(520px, 100%);
  padding: 40px 42px;
  border-radius: 20px;
  border: 1px solid rgba(99, 91, 158, 0.14);
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 24px 70px rgba(31, 35, 62, 0.14);
  backdrop-filter: blur(18px);
}

.login-brand {
  text-align: center;
  margin-bottom: 18px;
}

.login-title {
  margin: 0;
  color: #17162f;
  font-size: 32px;
  line-height: 1.2;
  font-weight: 780;
}

.login-subtitle {
  margin: 10px 0 0;
  color: #8a85a5;
  font-size: 15px;
  line-height: 1.4;
}

.login-hint {
  margin: 0 0 24px;
  padding: 12px 14px;
  border: 1px solid #e2def0;
  border-radius: 12px;
  background: #f7f4ff;
  color: #625d82;
  font-size: 14px;
  line-height: 1.5;
  text-align: center;
}

.login-form {
  margin: 0;
}

.login-label {
  display: block;
  margin: 16px 0 8px;
  color: #625d82;
  font-size: 13px;
  font-weight: 700;
}

:deep(.el-form-item) {
  margin-bottom: 0;
}

:deep(.el-input__wrapper) {
  height: 52px;
  padding: 0 14px;
  border-radius: 12px;
  background: #fff !important;
  box-shadow: 0 0 0 1px rgba(99, 91, 158, 0.16) inset !important;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(81, 70, 201, 0.34) inset !important;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(81, 70, 201, 0.92) inset !important;
}

:deep(.el-input__inner) {
  color: #17162f !important;
  -webkit-text-fill-color: #17162f !important;
  caret-color: #5146c9 !important;
  font-size: 15px;
  font-weight: 500;
}

:deep(.el-input__inner::placeholder) {
  color: #a5a0ba !important;
}

:deep(.el-input__prefix .el-icon),
:deep(.el-input__suffix .el-icon) {
  color: #8a85a5;
}

:deep(.el-input__inner:-webkit-autofill),
:deep(.el-input__inner:-webkit-autofill:hover),
:deep(.el-input__inner:-webkit-autofill:focus),
:deep(.el-input__inner:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 9999px #fff inset !important;
  -webkit-text-fill-color: #17162f !important;
  caret-color: #5146c9;
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
  color: #756f93;
  font-size: 12px;
  cursor: pointer;
}

.remember-check input {
  accent-color: #5146c9;
}

.login-link {
  border: 0;
  background: transparent;
  color: #5146c9;
  font: inherit;
  font-size: 12px;
  font-weight: 680;
  cursor: pointer;
}

.submit-btn {
  width: 100%;
  height: 52px;
  border: 0;
  border-radius: 12px;
  color: #fff;
  background: linear-gradient(180deg, #786cf0, #5146c9);
  font-size: 16px;
  font-weight: 760;
  letter-spacing: 0;
  box-shadow: 0 12px 24px rgba(81, 70, 201, 0.22);
}

.submit-btn:hover,
.submit-btn:focus {
  color: #fff;
}

.account-note {
  margin: 20px 0 0;
  color: #8a85a5;
  text-align: center;
  font-size: 13px;
  line-height: 1.5;
}

:global(html[data-theme="dark"]) .login-theme-toggle {
  border-color: rgba(148, 163, 184, 0.16);
  background: rgba(17, 19, 24, 0.72);
  color: rgba(203, 213, 225, 0.72);
}

:global(html[data-theme="dark"]) .login-page {
  background: linear-gradient(180deg, #090b10 0%, #111022 100%);
  color: #f8fafc;
}

:global(html[data-theme="dark"]) .login-card {
  border-color: rgba(148, 163, 184, 0.16);
  background: rgba(17, 19, 24, 0.86);
}

:global(html[data-theme="dark"]) .login-title {
  color: rgba(248, 250, 252, 0.94);
}

:global(html[data-theme="dark"]) .login-subtitle,
:global(html[data-theme="dark"]) .account-note {
  color: rgba(203, 213, 225, 0.66);
}

:global(html[data-theme="dark"]) .login-hint {
  border-color: rgba(148, 163, 184, 0.16);
  background: rgba(99, 91, 158, 0.16);
  color: rgba(248, 250, 252, 0.86);
}

:global(html[data-theme="dark"]) :deep(.el-input__wrapper) {
  background: #111827 !important;
  border-color: rgba(148, 163, 184, 0.16);
}

:global(html[data-theme="dark"]) :deep(.el-input__inner) {
  color: #f8fafc !important;
  -webkit-text-fill-color: #f8fafc !important;
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

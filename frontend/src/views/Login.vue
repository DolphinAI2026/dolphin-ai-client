<template>
  <div class="login-page">
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

    <div class="brand-panel">
      <div class="brand-content">
        <div class="brand-logo">
          <div class="logo-mark">AI</div>
          <span class="logo-text">Builder AI</span>
        </div>
        <p class="brand-sub">V3 · Builder / 智能搭建工作台</p>
        <ul class="feature-list">
          <li><span class="dot"></span>Builder 智能搭建：一句话生成可上线应用</li>
          <li><span class="dot"></span>SPEC 自动梳理角色、模型、表单和流程</li>
          <li><span class="dot"></span>自开发边界清晰交给睿鲸AI Coding</li>
          <li><span class="dot"></span>全代码项目接入 Vibe Coding 工作区</li>
        </ul>
      </div>
    </div>

    <div class="form-panel">
      <div class="form-card">
        <h2 class="form-title">登录 Builder</h2>
        <p class="form-subtitle">使用管理员创建的账号进入智能搭建工作台</p>

        <el-form
          :model="loginForm"
          :rules="loginRules"
          ref="loginFormRef"
          class="login-form"
          @submit.prevent="handleLogin"
        >
          <el-form-item prop="username">
            <el-input
              v-model="loginForm.username"
              placeholder="请输入用户名"
              size="large"
              :prefix-icon="User"
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
              :prefix-icon="Lock"
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

        <p class="account-note">账号由管理员统一创建；如需加入团队，请联系管理员在成员管理中添加。</p>
      </div>
    </div>
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
  --login-panel-bg: #ffffff;
  --login-text: #111827;
  --login-muted: #64748b;
  --login-subtle: #94a3b8;
  --login-border: #d8e1f0;
  --login-border-strong: #b8c7dd;
  --login-input-bg: #ffffff;
  --login-input-hover: #f8fbff;
  --login-focus: #6177f6;
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(520px, 64vw) minmax(380px, 1fr);
  background: var(--login-panel-bg);
  color: var(--login-text);
  overflow: hidden;
}

.login-theme-toggle {
  position: fixed;
  top: 24px;
  right: 26px;
  z-index: 5;
  height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid var(--login-border);
  background: color-mix(in srgb, var(--login-panel-bg) 88%, transparent);
  color: var(--login-muted);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  backdrop-filter: blur(14px);
  transition: border-color 0.18s ease, color 0.18s ease, background 0.18s ease;
}

.login-theme-toggle:hover {
  color: var(--login-text);
  border-color: var(--login-border-strong);
  background: var(--login-input-hover);
}

.brand-panel {
  position: relative;
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 72px;
  overflow: hidden;
  background:
    radial-gradient(circle at 92% 18%, rgba(255, 255, 255, 0.14) 0 18%, transparent 18.4%),
    radial-gradient(circle at 0 100%, rgba(255, 255, 255, 0.10) 0 20%, transparent 20.4%),
    linear-gradient(135deg, #3123b8 0%, #4932dc 46%, #667dff 100%);
}

.brand-panel::before,
.brand-panel::after {
  content: "";
  position: absolute;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  pointer-events: none;
}

.brand-panel::before {
  width: 420px;
  height: 420px;
  right: -68px;
  top: -88px;
}

.brand-panel::after {
  width: 300px;
  height: 300px;
  right: 116px;
  bottom: 160px;
}

.brand-content {
  position: relative;
  z-index: 1;
  width: min(420px, 100%);
  color: #fff;
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 18px;
}

.logo-mark {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 21px;
  font-weight: 800;
  letter-spacing: 0;
  background:
    radial-gradient(circle at 28% 22%, #70f1ff 0 16%, transparent 17%),
    linear-gradient(145deg, #19b7d4 0%, #4659ff 50%, #1b2abf 100%);
  box-shadow: 0 14px 40px rgba(8, 21, 84, 0.32);
}

.logo-text {
  color: #fff;
  font-size: 32px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: 0;
}

.brand-sub {
  margin: 0 0 52px 58px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 17px;
  line-height: 1.5;
}

.feature-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 24px;
  margin: 0 0 0 6px;
  padding: 0;
}

.feature-list li {
  display: flex;
  align-items: center;
  gap: 18px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 16px;
  font-weight: 500;
  letter-spacing: 0;
}

.feature-list .dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.58);
}

.form-panel {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 80px 56px;
  background: var(--login-panel-bg);
}

.form-card {
  width: 100%;
  max-width: 420px;
}

.form-title {
  margin: 0 0 10px;
  color: var(--login-text);
  font-size: 26px;
  font-weight: 800;
  letter-spacing: 0;
}

.form-subtitle {
  margin: 0 0 34px;
  color: var(--login-muted);
  font-size: 14px;
  line-height: 1.5;
}

.login-form {
  margin-top: 2px;
}

:deep(.el-form-item) {
  margin-bottom: 22px;
}

:deep(.el-input__wrapper) {
  height: 54px;
  padding: 0 18px;
  border-radius: 10px;
  background: var(--login-input-bg) !important;
  box-shadow: 0 0 0 1px var(--login-border) inset !important;
  transition: box-shadow 0.18s ease, background 0.18s ease;
}

:deep(.el-input__wrapper:hover) {
  background: var(--login-input-hover) !important;
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--login-focus) 45%, var(--login-border-strong)) inset !important;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px var(--login-focus) inset !important;
}

:deep(.el-input__inner) {
  color: var(--login-text) !important;
  -webkit-text-fill-color: var(--login-text) !important;
  caret-color: var(--login-text) !important;
  font-size: 15px;
  font-weight: 500;
}

:deep(.el-input__inner::selection) {
  color: #0f172a;
  background: #dbe7ff;
  -webkit-text-fill-color: #0f172a;
}

:deep(.el-input__inner::placeholder) {
  color: var(--login-subtle) !important;
  -webkit-text-fill-color: var(--login-subtle) !important;
  opacity: 1;
  font-weight: 400;
}

:deep(.el-input__prefix .el-icon),
:deep(.el-input__suffix .el-icon) {
  color: var(--login-muted);
}

:deep(.el-input__inner:-webkit-autofill),
:deep(.el-input__inner:-webkit-autofill:hover),
:deep(.el-input__inner:-webkit-autofill:focus),
:deep(.el-input__inner:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 9999px var(--login-input-bg) inset !important;
  -webkit-text-fill-color: var(--login-text) !important;
  caret-color: var(--login-text);
  transition: background-color 9999s ease-in-out 0s;
}

.account-note {
  margin: 16px 0 0;
  color: var(--login-muted);
  font-size: 12px;
  line-height: 1.6;
}

.submit-btn {
  width: 100%;
  height: 52px;
  border: 0;
  border-radius: 10px;
  color: #fff;
  background: linear-gradient(135deg, #3426c6 0%, #4a39dc 48%, #667dff 100%);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0;
  box-shadow: 0 16px 36px rgba(79, 70, 229, 0.18);
  transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease;
}

.submit-btn:hover,
.submit-btn:focus {
  color: #fff;
  filter: brightness(1.03);
  transform: translateY(-1px);
  box-shadow: 0 20px 42px rgba(79, 70, 229, 0.24);
}

.submit-btn:active {
  transform: translateY(0);
}

:global(html[data-theme="dark"]) .login-page {
  --login-panel-bg: #090b10;
  --login-text: #f8fafc;
  --login-muted: #a7b0c0;
  --login-subtle: #64748b;
  --login-border: rgba(148, 163, 184, 0.22);
  --login-border-strong: rgba(148, 163, 184, 0.36);
  --login-input-bg: #10141c;
  --login-input-hover: #131925;
  --login-focus: #8190ff;
  background: var(--login-panel-bg);
}

:global(html[data-theme="dark"]) .brand-panel {
  background:
    radial-gradient(circle at 92% 18%, rgba(255, 255, 255, 0.10) 0 18%, transparent 18.4%),
    radial-gradient(circle at 0 100%, rgba(255, 255, 255, 0.07) 0 20%, transparent 20.4%),
    linear-gradient(135deg, #14115c 0%, #2520a3 45%, #4356ef 100%);
}

:global(html[data-theme="dark"]) .form-panel {
  background: var(--login-panel-bg);
}

:global(html[data-theme="dark"]) .login-theme-toggle {
  background: rgba(17, 19, 24, 0.82);
}

@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .brand-panel {
    min-height: auto;
    padding: 44px 32px;
    place-items: start;
  }

  .brand-content {
    width: 100%;
  }

  .brand-sub {
    margin-bottom: 28px;
  }

  .feature-list {
    gap: 14px;
  }

  .form-panel {
    min-height: auto;
    align-items: flex-start;
    padding: 42px 28px 56px;
  }
}

@media (max-width: 560px) {
  .login-theme-toggle {
    top: 14px;
    right: 14px;
  }

  .brand-panel {
    padding: 56px 24px 32px;
  }

  .logo-text {
    font-size: 26px;
  }

  .brand-sub {
    margin-left: 0;
  }

  .form-panel {
    padding: 32px 20px 48px;
  }
}
</style>

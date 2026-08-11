<template>
  <div :class="['login-page', { 'theme-dark': themeStore.isDark }]">
    <img class="login-brand-watermark" :src="ruijingWhaleMarkUrl" alt="" aria-hidden="true" />

    <button
      type="button"
      class="login-theme-toggle"
      :title="themeStore.isDark ? '切换到浅色模式' : '切换到深色模式'"
      @click="themeStore.toggle()"
    >
      <el-icon>
        <Sunny v-if="themeStore.isDark" />
        <Moon v-else />
      </el-icon>
      <span>{{ themeStore.isDark ? '浅色' : '深色' }}</span>
    </button>

    <main class="login-shell">
      <section class="login-brand-stage" aria-label="Dolphin Code 品牌背景">
        <img class="login-brand-mark-large" :src="ruijingWhaleMarkUrl" alt="" aria-hidden="true" />
      </section>

      <section class="login-auth-panel" aria-label="登录Dolphin Code">
        <div class="login-card">
          <div class="login-card-top">
            <div class="login-header">
              <img class="login-logo" :src="ruijingWhaleMarkUrl" alt="" aria-hidden="true" />
              <div class="login-header-copy">
                <h1>Dolphin Code</h1>
                <p>登录以打开桌面工作台</p>
              </div>
            </div>
            <el-tooltip v-if="desktopService" content="更改登录服务" placement="top">
              <button
                type="button"
                class="login-service-settings"
                :disabled="!desktopServiceChangeAllowed"
                aria-label="更改登录服务"
                :aria-busy="changingDesktopService"
                @click="changeDesktopService"
              >
                <el-icon><Setting /></el-icon>
              </button>
            </el-tooltip>
          </div>

          <div v-if="desktopService" class="login-service-row" aria-label="当前登录服务">
            <span class="service-status-dot" aria-hidden="true" />
            <span class="service-name">{{ desktopService.label }}</span>
            <span class="service-meta">{{ desktopService.provider === 'apaas' ? 'aPaaS 认证' : 'Control Plane 认证' }}</span>
            <span class="service-host">{{ desktopService.host }}</span>
            <span v-for="product in desktopService.products" :key="product" class="service-product">{{ product }}</span>
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
                placeholder="账号"
                size="large"
                :prefix-icon="User"
                :disabled="changingDesktopService"
                autocomplete="username"
                clearable
              />
            </el-form-item>

            <el-form-item prop="password" class="login-field-item">
              <el-input
                v-model="loginForm.password"
                type="password"
                placeholder="密码"
                size="large"
                :prefix-icon="Lock"
                :disabled="loginLoading || changingDesktopService"
                autocomplete="current-password"
                show-password
                @keyup.enter="handleLogin"
              />
            </el-form-item>

            <el-form-item
              v-if="captchaRequired"
              prop="captcha_code"
              class="login-field-item"
            >
              <div class="captcha-row">
                <el-input
                  v-model="loginForm.captcha_code"
                  placeholder="验证码"
                  size="large"
                  maxlength="6"
                  :disabled="loginLoading || changingDesktopService"
                  @keyup.enter="handleLogin"
                />
                <button
                  type="button"
                  class="captcha-image-button"
                  title="刷新验证码"
                  :disabled="changingDesktopService"
                  @click="refreshCaptcha"
                >
                  <img v-if="captchaImage" :src="captchaImage" alt="验证码" />
                  <span v-else>刷新</span>
                </button>
              </div>
            </el-form-item>

            <el-form-item class="login-submit-item">
              <el-button
                type="primary"
                size="large"
                :loading="loginLoading"
                :disabled="loginLoading || changingDesktopService"
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

<script lang="ts">
export function canChangeDesktopService(
  loginPending: boolean,
  transitionPending: boolean,
): boolean {
  return !loginPending && !transitionPending
}

export function tryStartLogin(
  loginPending: boolean,
  transitionPending: boolean,
  start: () => void,
): boolean {
  if (loginPending || transitionPending) return false
  start()
  return true
}
</script>

<script setup lang="ts">
import { computed, onMounted, ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, Moon, Setting, Sunny, User } from '@element-plus/icons-vue'
import { authApi } from '@/api/auth'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'
import ruijingWhaleMarkUrl from '@/assets/brand/ruijing-whale-mark.svg'
import { recoverWebConsoleRedirect } from '@/auth/webConsoleSession'
import { resolveExternalLoginRedirect, safeLoginRedirectPath } from '@/router/loginRedirect'
import {
  defaultProductHome,
  loadProductAvailability,
  productForRoute,
  redirectForDisabledProduct,
} from '@/stores/productAvailability'
import {
  enterDesktopLoginSetup,
  getDesktopState,
  isDesktop,
  type DesktopDiscoveryDocument,
  type DesktopLoginMode,
} from '@/utils/desktop'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()

const loginFormRef = ref<FormInstance>()
const loginLoading = ref(false)
const captchaRequired = ref(false)
const captchaProbeFailed = ref(false)
const captchaId = ref('')
const captchaImage = ref('')
type DesktopServiceSummary = {
  label: string
  host: string
  provider: DesktopLoginMode
  products: string[]
}

const desktopService = ref<DesktopServiceSummary | null>(null)
const changingDesktopService = ref(false)
const desktopServiceChangeAllowed = computed(() => canChangeDesktopService(
  loginLoading.value,
  changingDesktopService.value,
))

const loginForm = reactive({
  username: '',
  password: '',
  captcha_code: '',
})

const loginRules: FormRules = {
  username: [{ required: true, message: '请输入账号', trigger: ['blur', 'change'] }],
  password: [{ required: true, message: '请输入密码', trigger: ['blur', 'change'] }],
  captcha_code: [{
    validator: (_rule, value, callback) => {
      if (captchaRequired.value && !String(value || '').trim()) {
        callback(new Error('请输入验证码'))
        return
      }
      callback()
    },
    trigger: ['blur', 'change'],
  }],
}

const refreshCaptcha = async (): Promise<boolean> => {
  if (changingDesktopService.value) return false
  try {
    const result = await authApi.getCaptcha()
    captchaRequired.value = result.required
    captchaId.value = result.captcha_id || ''
    captchaImage.value = result.image_data || ''
    loginForm.captcha_code = ''
    return true
  } catch {
    captchaRequired.value = false
    captchaId.value = ''
    captchaImage.value = ''
    loginForm.captcha_code = ''
    return false
  }
}

const probeCaptcha = async () => {
  captchaProbeFailed.value = !(await refreshCaptcha())
}

async function loadDesktopService() {
  if (!isDesktop) return
  try {
    const snapshot = await getDesktopState()
    const config = snapshot.config
    if (!config) return
    const discovery: DesktopDiscoveryDocument | null = config.discovery || null
    const provider = discovery?.auth.provider || config.login.mode
    const loginUrl = discovery?.auth.login_url || config.login.base_url
    const products = discovery
      ? [
          discovery.products.builder.enabled ? 'Builder' : '',
          discovery.products.code.enabled ? 'Code' : '',
        ].filter(Boolean)
      : []
    desktopService.value = {
      label: discovery?.platform.name || (provider === 'apaas' ? 'aPaaS平台' : 'AI中台'),
      host: new URL(loginUrl).host,
      provider,
      products,
    }
  } catch {
    desktopService.value = null
  }
}

async function changeDesktopService() {
  if (!isDesktop || !desktopServiceChangeAllowed.value) return
  changingDesktopService.value = true
  try {
    userStore.logout()
    if (__DESKTOP_WEB_PREVIEW__) {
      await router.replace('/desktop-setup')
    } else {
      await enterDesktopLoginSetup()
    }
  } catch {
    changingDesktopService.value = false
    ElMessage.error('无法打开登录服务设置，请稍后重试')
  }
}

const recoverExistingWebConsoleSession = async () => {
  try {
    const target = await recoverWebConsoleRedirect(
      route.query.redirect,
      Boolean(userStore.token),
    )
    if (target) window.location.replace(target)
  } catch {
    // Keep the login form available when the cached aPaaS session is no longer usable.
  }
}

onMounted(() => {
  void probeCaptcha()
  void loadDesktopService()
  void recoverExistingWebConsoleSession()
})

const handleLogin = async () => {
  const form = loginFormRef.value
  if (!form || !tryStartLogin(
    loginLoading.value,
    changingDesktopService.value,
    () => { loginLoading.value = true },
  )) return

  try {
    const valid = await form.validate().catch(() => false)
    if (!valid || changingDesktopService.value) return

    try {
      const result = await userStore.login(
        loginForm.username,
        loginForm.password,
        captchaId.value,
        loginForm.captcha_code,
      )

      if (result.requiresSelection) {
        const redirect = safeLoginRedirectPath(route.query.redirect)
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
        const externalRedirect = resolveExternalLoginRedirect(route.query.redirect)
        if (externalRedirect) {
          window.location.replace(externalRedirect)
          return
        }
        const productAvailability = await loadProductAvailability()
        const redirect = safeLoginRedirectPath(route.query.redirect) || result.entryPath
        const disabledProductRedirect = redirectForDisabledProduct(
          productAvailability,
          productForRoute(router.resolve(redirect || defaultProductHome(productAvailability))),
        )
        router.replace(disabledProductRedirect || redirect || defaultProductHome(productAvailability))
      }
    } catch (error: any) {
      const detail =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        error?.message ||
        '登录失败，请检查用户名和密码'
      ElMessage.error(detail)
      if (captchaRequired.value) {
        await refreshCaptcha()
      } else if (captchaProbeFailed.value) {
        captchaProbeFailed.value = false
        await refreshCaptcha()
      }
    }
  } finally {
    loginLoading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  overflow: hidden;
  position: relative;
  color: #0b1b3f;
  background:
    linear-gradient(115deg, rgba(232, 244, 255, 0.92) 0%, rgba(248, 250, 252, 0.98) 44%, rgba(241, 245, 249, 1) 100%);
}

.login-theme-toggle {
  position: fixed;
  top: 22px;
  right: 26px;
  z-index: 10;
  height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: rgba(255, 255, 255, 0.9);
  color: #3f4d6b;
  font-size: 12px;
  font-weight: 600;
  box-shadow: 0 10px 30px rgba(11, 27, 63, 0.08);
  backdrop-filter: blur(16px);
  cursor: pointer;
}

.login-theme-toggle:hover {
  background: #fff;
  color: #075fa8;
  border-color: rgba(37, 99, 235, 0.28);
}

.login-shell {
  position: relative;
  z-index: 1;
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1fr) clamp(500px, 34vw, 620px);
  align-items: stretch;
}

.login-brand-stage {
  position: relative;
  overflow: hidden;
  min-height: 100vh;
  background:
    linear-gradient(90deg, rgba(7, 61, 139, 0.09) 0 1px, transparent 1px 100%),
    linear-gradient(0deg, rgba(7, 61, 139, 0.06) 0 1px, transparent 1px 100%);
  background-size: 96px 96px;
  mask-image: linear-gradient(90deg, #000 0%, rgba(0, 0, 0, 0.72) 42%, transparent 86%);
}

.login-brand-stage::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(135deg, rgba(7, 61, 139, 0.2), rgba(28, 201, 217, 0.06) 48%, transparent 72%);
}

.login-brand-stage::after {
  content: "";
  position: absolute;
  left: 14%;
  top: 23%;
  width: min(44vw, 620px);
  height: 42vh;
  border-top: 1px solid rgba(7, 95, 168, 0.18);
  border-left: 1px solid rgba(7, 95, 168, 0.12);
  transform: skewX(-18deg);
  opacity: 0.55;
}

.login-brand-mark-large {
  position: absolute;
  left: clamp(48px, 8vw, 148px);
  top: 50%;
  width: min(42vw, 540px);
  max-width: 58vh;
  opacity: 0.13;
  transform: translateY(-50%);
  filter: saturate(1.08);
  user-select: none;
  pointer-events: none;
}

.login-brand-watermark {
  position: fixed;
  left: -12vw;
  bottom: -18vh;
  width: min(48vw, 760px);
  opacity: 0.055;
  transform: rotate(-7deg);
  user-select: none;
  pointer-events: none;
}

.login-auth-panel {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 88px clamp(48px, 5vw, 88px);
}

.login-card {
  position: relative;
  width: min(420px, 100%);
  padding: 34px 36px 34px;
  border: 1px solid rgba(11, 27, 63, 0.08);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow:
    0 24px 64px rgba(11, 27, 63, 0.1),
    0 1px 2px rgba(11, 27, 63, 0.06);
  backdrop-filter: blur(18px);
}

.login-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.login-header {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.login-logo {
  width: 48px;
  height: 48px;
  display: block;
  flex: 0 0 auto;
  border-radius: 12px;
  box-shadow: 0 10px 24px rgba(7, 95, 168, 0.22);
}

.login-header h1 {
  margin: 0;
  color: #0b1b3f;
  font-size: 27px;
  line-height: 1.15;
  font-weight: 800;
  letter-spacing: 0;
}

.login-header p {
  margin: 7px 0 0;
  color: #64748b;
  font-size: 14px;
  line-height: 1.5;
}

.login-header-copy {
  min-width: 0;
  flex: 1;
}

.login-service-settings {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  margin-top: 2px;
  border: 1px solid rgba(11, 27, 63, 0.1);
  border-radius: 8px;
  background: rgba(248, 250, 252, 0.8);
  color: #64748b;
  cursor: pointer;
  transition: color 160ms ease, border-color 160ms ease, background 160ms ease;
}

.login-service-settings:hover:not(:disabled) {
  border-color: rgba(29, 78, 216, 0.28);
  background: #fff;
  color: #1d4ed8;
}

.login-service-settings:focus-visible {
  outline: 2px solid rgba(29, 78, 216, 0.28);
  outline-offset: 3px;
}

.login-service-settings:disabled {
  cursor: wait;
  opacity: 0.55;
}

.login-service-row {
  min-width: 0;
  min-height: 34px;
  margin-bottom: 24px;
  padding: 7px 10px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  border: 1px solid rgba(11, 27, 63, 0.08);
  border-radius: 8px;
  background: rgba(248, 250, 252, 0.72);
  color: #475569;
  font-size: 12px;
  line-height: 18px;
}

.service-status-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #16a34a;
  box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.12);
}

.service-name {
  min-width: 0;
  max-width: 100%;
  color: #1e293b;
  font-weight: 650;
  overflow-wrap: anywhere;
}

.service-meta,
.service-host {
  color: #64748b;
  overflow-wrap: anywhere;
}

.service-product {
  padding: 1px 6px;
  border: 1px solid rgba(29, 78, 216, 0.16);
  border-radius: 999px;
  color: #3157b7;
  background: rgba(219, 234, 254, 0.5);
  font-size: 11px;
  line-height: 16px;
}

.login-form {
  margin: 0;
}

.captcha-row {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 128px;
  gap: 10px;
}

.captcha-image-button {
  width: 128px;
  height: 52px;
  padding: 0;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
  cursor: pointer;
}

.captcha-image-button img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
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
  background: rgba(248, 250, 252, 0.92) !important;
  box-shadow: 0 0 0 1px #e2e8f0 inset !important;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #cbd5e1 inset !important;
}

:deep(.el-input__wrapper.is-focus) {
  background: #fff !important;
  box-shadow: 0 0 0 2px #075fa8 inset !important;
}

:deep(.el-input__inner) {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
  caret-color: #075fa8 !important;
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
  background: #1d4ed8 !important;
  border-color: #1d4ed8 !important;
  font-size: 15px;
  font-weight: 700;
  box-shadow: 0 10px 24px rgba(29, 78, 216, 0.22);
}

.submit-btn:hover,
.submit-btn:focus {
  color: #fff;
  background: #1e40af !important;
  border-color: #1e40af !important;
}

.submit-btn:focus-visible {
  outline: 2px solid rgba(29, 78, 216, 0.28);
  outline-offset: 3px;
}

.login-page.theme-dark {
  background:
    linear-gradient(115deg, #071123 0%, #0b1224 48%, #10192f 100%);
  color: #f8fafc;
}

.login-page.theme-dark .login-brand-stage {
  background:
    linear-gradient(90deg, rgba(96, 165, 250, 0.08) 0 1px, transparent 1px 100%),
    linear-gradient(0deg, rgba(96, 165, 250, 0.06) 0 1px, transparent 1px 100%);
  background-size: 96px 96px;
}

.login-page.theme-dark .login-brand-stage::before {
  background:
    linear-gradient(135deg, rgba(96, 165, 250, 0.16), rgba(34, 211, 238, 0.07) 48%, transparent 72%);
}

.login-page.theme-dark .login-card {
  border-color: rgba(255, 255, 255, 0.08);
  background: rgba(19, 26, 46, 0.88);
  box-shadow:
    0 28px 80px rgba(0, 0, 0, 0.34),
    0 1px 2px rgba(0, 0, 0, 0.2);
}

.login-page.theme-dark .login-theme-toggle {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(15, 23, 42, 0.86);
  color: #e2e8f0;
}

.login-page.theme-dark .login-header h1 {
  color: #f8fafc;
}

.login-page.theme-dark .login-header p {
  color: #94a3b8;
}

.login-page.theme-dark .login-service-settings {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(15, 23, 42, 0.72);
  color: #94a3b8;
}

.login-page.theme-dark .login-service-settings:hover:not(:disabled) {
  border-color: rgba(96, 165, 250, 0.45);
  background: rgba(30, 41, 59, 0.92);
  color: #93c5fd;
}

.login-page.theme-dark .login-service-row {
  color: #94a3b8;
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(15, 23, 42, 0.58);
}

.login-page.theme-dark .service-name {
  color: #e2e8f0;
}

.login-page.theme-dark .service-meta,
.login-page.theme-dark .service-host {
  color: #94a3b8;
}

.login-page.theme-dark .service-product {
  border-color: rgba(147, 197, 253, 0.22);
  color: #bfdbfe;
  background: rgba(30, 64, 175, 0.28);
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
  background: #2563eb !important;
  border-color: #2563eb !important;
}

.login-page.theme-dark .submit-btn:hover,
.login-page.theme-dark .submit-btn:focus {
  background: #3b82f6 !important;
  border-color: #3b82f6 !important;
  color: #fff;
}

@media (max-width: 980px) {
  .login-page {
    overflow: auto;
  }

  .login-shell {
    grid-template-columns: 1fr;
    align-items: center;
  }

  .login-brand-stage {
    position: absolute;
    inset: 0;
    min-height: 100%;
    opacity: 0.7;
  }

  .login-brand-mark-large {
    left: 50%;
    top: 42%;
    width: min(76vw, 520px);
    transform: translate(-50%, -50%);
    opacity: 0.08;
  }

  .login-auth-panel {
    min-height: 100vh;
    padding: 88px 32px 64px;
  }
}

@media (max-width: 620px) {
  .login-theme-toggle {
    top: 14px;
    right: 14px;
  }

  .login-auth-panel {
    padding: 78px 20px 40px;
  }

  .login-card {
    width: 100%;
    padding: 26px 22px 24px;
    border-radius: 10px;
  }

  .login-header {
    gap: 12px;
  }

  .login-logo {
    width: 42px;
    height: 42px;
    border-radius: 10px;
  }

  .login-header h1 {
    font-size: 23px;
  }

  .login-header p {
    font-size: 13px;
  }

  .login-brand-watermark {
    display: none;
  }
}
</style>

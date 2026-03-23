<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-header">
        <div class="logo-mark">A</div>
        <h1 class="brand-title">aPaaS Builder AI</h1>
        <p class="brand-desc">得帆云智能搭建助手</p>
      </div>

      <el-tabs v-model="activeTab" class="login-tabs">
        <el-tab-pane label="登录" name="login">
          <el-form :model="loginForm" :rules="loginRules" ref="loginFormRef" @submit.prevent="handleLogin">
            <el-form-item prop="username">
              <el-input
                v-model="loginForm.username"
                placeholder="请输入用户名"
                size="large"
                prefix-icon="User"
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
      ElMessage.error(error.response?.data?.detail || '登录失败，请检查用户名和密码')
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
      ElMessage.error(error.response?.data?.detail || '注册失败')
    } finally {
      registerLoading.value = false
    }
  })
}
</script>

<style scoped>
/* ── Dark theme login ── */
.login-container {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #0a0a0a;
  padding: 20px;
}

.login-box {
  width: 100%;
  max-width: 420px;
  background: #111;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 16px;
  padding: 40px;
}

/* ── Header / Logo ── */
.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.logo-mark {
  width: 52px;
  height: 52px;
  margin: 0 auto 18px;
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -1px;
}

.brand-title {
  margin: 0 0 6px 0;
  font-size: 26px;
  font-weight: 700;
  background: linear-gradient(135deg, #c4b5fd, #7c3aed);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.brand-desc {
  margin: 0;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.4);
}

/* ── Tabs ── */
.login-tabs {
  margin-top: 24px;
}

.login-tabs :deep(.el-tabs__header) {
  margin-bottom: 24px;
}

.login-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.login-tabs :deep(.el-tabs__item) {
  font-size: 15px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.45);
  transition: color 0.2s;
}

.login-tabs :deep(.el-tabs__item:hover) {
  color: rgba(255, 255, 255, 0.7);
}

.login-tabs :deep(.el-tabs__item.is-active) {
  color: #c4b5fd;
}

.login-tabs :deep(.el-tabs__active-bar) {
  background: linear-gradient(135deg, #7c3aed, #6366f1);
}

/* ── Input fields ── */
:deep(.el-input__wrapper) {
  background: #161622;
  border-radius: 10px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.08) inset;
  transition: all 0.25s;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.15) inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #7c3aed inset;
}

:deep(.el-input__inner) {
  color: #fff;
}

:deep(.el-input__inner::placeholder) {
  color: rgba(255, 255, 255, 0.3);
}

:deep(.el-input__prefix .el-icon) {
  color: rgba(255, 255, 255, 0.35);
}

:deep(.el-input__suffix .el-icon) {
  color: rgba(255, 255, 255, 0.35);
}

/* ── Form items ── */
:deep(.el-form-item) {
  margin-bottom: 20px;
}

:deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

:deep(.el-form-item__error) {
  color: #f87171;
}

/* ── Submit button ── */
.submit-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  border: none;
  border-radius: 10px;
  color: #fff;
  transition: all 0.25s;
}

.submit-btn:hover,
.submit-btn:focus {
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(124, 58, 237, 0.35);
}

.submit-btn:active {
  transform: translateY(0);
  box-shadow: none;
}
</style>

<template>
  <div class="login-bg">
    <div class="login-card">
      <div class="login-brand">MCP 管理平台</div>
      <div class="login-sub">MCP 接入与测试平台</div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="onSubmit"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="admin"
            autocomplete="username"
          />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="error"
          show-icon
          :closable="false"
          style="margin-bottom: 12px"
        />

        <el-button
          type="primary"
          class="login-submit"
          :loading="loading"
          @click="onSubmit"
        >
          登录
        </el-button>
      </el-form>

      <div class="login-foot">
        租户、用户和权限从 aPaaS 读取，平台只管理 MCP 接入、测试和日志。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth   = useAuthStore()

const formRef = ref<FormInstance | null>(null)
const form    = reactive({ username: '', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const loading  = ref(false)
const errorMsg = ref('')

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  errorMsg.value = ''
  try {
    await auth.login(form.username, form.password)
    router.push('/status')
  } catch (err: any) {
    errorMsg.value = err?.response?.data?.detail || err?.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-bg {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(circle at 18% 18%, rgba(91, 210, 145, .45), transparent 320px),
    radial-gradient(circle at 82% 78%, rgba(24, 82, 61, .55), transparent 360px),
    linear-gradient(135deg, #101915 0%, #1f3029 100%);
}
.login-card {
  background: #fff;
  border-radius: 12px;
  padding: 32px 40px;
  width: 360px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.2);
}
.login-brand {
  font-size: 22px;
  font-weight: 700;
  color: #17211d;
  text-align: center;
}
.login-sub {
  font-size: 13px;
  color: #8a93a6;
  text-align: center;
  margin-bottom: 24px;
}
.login-submit {
  width: 100%;
}
.login-foot {
  margin-top: 16px;
  font-size: 12px;
  color: #999;
  text-align: center;
  line-height: 1.6;
}
</style>

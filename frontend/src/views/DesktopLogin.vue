<template>
  <div class="desktop-login">
    <div class="card">
      <h1>睿鲸 Builder</h1>
      <p class="sub">登录以打开桌面工作台</p>
      <el-input v-model="form.username" placeholder="账号" size="large" />
      <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password
                @keyup.enter="onSubmit" style="margin-top:12px" />
      <el-button type="primary" size="large" :loading="loading" style="width:100%;margin-top:16px" @click="onSubmit">登录</el-button>
      <p v-if="err" class="err">{{ err }}</p>
    </div>
  </div>
</template>
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = useRouter(); const route = useRoute(); const store = useUserStore()
const form = reactive({ username: '', password: '' })
const loading = ref(false); const err = ref('')

async function onSubmit() {
  if (!form.username || !form.password) { err.value = '请输入账号和密码'; return }
  loading.value = true; err.value = ''
  try {
    await store.desktopLogin(form.username, form.password)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.replace(redirect && !redirect.startsWith('/login') ? redirect : '/')
  } catch (e: any) {
    err.value = e?.response?.data?.detail || '登录失败'
  } finally { loading.value = false }
}
</script>
<style scoped>
.desktop-login{height:100vh;display:flex;align-items:center;justify-content:center;background:#f5f6fa}
.card{width:360px;padding:40px;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.08)}
.card h1{margin:0 0 4px;font-size:24px}
.sub{color:#888;margin:0 0 24px;font-size:14px}
.err{color:#f56c6c;font-size:13px;margin-top:12px}
</style>

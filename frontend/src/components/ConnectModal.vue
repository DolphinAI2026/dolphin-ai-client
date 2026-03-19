<template>
  <el-dialog v-model="visible" title="连接得帆云平台" width="480px" :close-on-click-modal="false">
    <p style="font-size:13px;color:#909399;margin-bottom:16px">连接到得帆云aPaaS平台以启用应用生成功能</p>

    <el-tabs v-model="mode" style="margin-bottom:8px">
      <el-tab-pane label="账号登录" name="login" />
      <el-tab-pane label="Token直连" name="token" />
    </el-tabs>

    <el-form :model="form" label-position="top" size="default">
      <el-form-item label="平台地址">
        <el-input v-model="form.baseUrl" placeholder="https://your-apaas.com/backend" />
      </el-form-item>
      <el-form-item label="租户ID">
        <el-input v-model="form.tenantId" placeholder="租户ID" />
      </el-form-item>

      <!-- 账号登录模式 -->
      <template v-if="mode === 'login'">
        <el-form-item label="用户名（手机号/邮箱）">
          <el-input v-model="form.username" placeholder="请输入登录账号" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" />
        </el-form-item>
      </template>

      <!-- Token直连模式 -->
      <template v-else>
        <el-form-item label="Token">
          <el-input v-model="form.token" type="textarea" :rows="3" placeholder="从浏览器F12复制xdaptoken值" />
        </el-form-item>
      </template>
<!-- APPEND_MARKER -->
      <el-alert v-if="mode === 'token'" type="info" :closable="false" show-icon style="margin-top:4px">
        <template #title>
          <span style="font-size:12px">登录aPaaS → F12 → Network → 复制请求头中的 xdaptoken 值</span>
        </template>
      </el-alert>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleConnect">
        {{ mode === 'login' ? '登录并连接' : '连接' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { usePreviewStore } from '@/stores/preview'
import request from '@/utils/request'

const visible = defineModel<boolean>({ default: false })
const previewStore = usePreviewStore()

const mode = ref('login')
const loading = ref(false)

// 从 localStorage 读取上次连接信息，没有则为空
const savedConn = JSON.parse(localStorage.getItem('apaas_connection') || '{}')
const form = reactive({
  baseUrl: savedConn.baseUrl || '',
  tenantId: savedConn.tenantId || '',
  username: savedConn.username || '',
  password: '',
  token: ''
})

const handleConnect = async () => {
  loading.value = true
  try {
    if (mode.value === 'login') {
      if (!form.username || !form.password) {
        ElMessage.warning('请输入用户名和密码')
        return
      }
      const res = await request.post('/apaas/login', {
        username: form.username,
        password: form.password,
        base_url: form.baseUrl,
        tenant_id: form.tenantId
      })
      if (res.status === 'ok') {
        previewStore.connected = true
        visible.value = false
        // 记住连接信息（不存密码）
        localStorage.setItem('apaas_connection', JSON.stringify({
          baseUrl: form.baseUrl, tenantId: form.tenantId, username: form.username
        }))
        ElMessage.success('登录成功，已连接得帆云平台')
      }
    } else {
      if (!form.token.trim()) {
        ElMessage.warning('请输入Token')
        return
      }
      const res = await request.post('/apaas/connect', {
        token: form.token.trim(),
        base_url: form.baseUrl,
        tenant_id: form.tenantId
      })
      if (res.status === 'ok') {
        previewStore.connected = true
        visible.value = false
        localStorage.setItem('apaas_connection', JSON.stringify({
          baseUrl: form.baseUrl, tenantId: form.tenantId
        }))
        ElMessage.success('已连接得帆云平台')
      }
    }
  } catch (e: any) {
    const detail = e.response?.data?.detail || '连接失败，请检查参数'
    ElMessage.error(detail)
  } finally {
    loading.value = false
  }
}
</script>
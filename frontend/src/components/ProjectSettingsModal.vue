<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '项目设置' : '新建项目'"
    width="520px"
    :close-on-click-modal="false"
    class="project-settings-modal"
  >
    <el-form :model="form" label-position="top" size="default">
      <!-- 基本信息 -->
      <el-form-item label="项目名称" required>
        <el-input v-model="form.name" placeholder="例如：劳务管理系统" />
      </el-form-item>
      <el-form-item label="项目描述">
        <el-input v-model="form.description" type="textarea" :rows="2" placeholder="简要描述项目用途" />
      </el-form-item>

      <!-- 平台环境配置（仅编辑模式显示） -->
      <template v-if="isEdit">
        <el-divider content-position="left">平台环境配置</el-divider>

        <el-form-item label="平台地址">
          <el-input v-model="form.platform_url" placeholder="https://your-apaas.com/backend/" />
        </el-form-item>
        <el-form-item label="租户ID">
          <el-input v-model="form.platform_tenant_id" placeholder="平台租户ID" />
        </el-form-item>

        <el-tabs v-model="connectMode" style="margin-bottom: 8px">
          <el-tab-pane label="账号登录" name="login" />
          <el-tab-pane label="Token直连" name="token" />
        </el-tabs>

        <template v-if="connectMode === 'login'">
          <el-form-item label="用户名（手机号/邮箱）">
            <el-input v-model="loginForm.username" placeholder="请输入登录账号" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="loginForm.password" type="password" show-password placeholder="请输入密码" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="connecting" @click="handleConnect" :disabled="!canConnect">
              登录并连接平台
            </el-button>
            <el-tag v-if="form.platform_connected" type="success" size="small" style="margin-left: 8px">已连接</el-tag>
            <el-tag v-else type="info" size="small" style="margin-left: 8px">未连接</el-tag>
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="Token">
            <el-input v-model="tokenForm.token" type="textarea" :rows="3" placeholder="从浏览器F12复制xdaptoken值" />
          </el-form-item>
          <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px">
            <template #title>
              <span style="font-size: 12px">登录aPaaS平台 -> F12 -> Network -> 复制请求头中的 xdaptoken 值</span>
            </template>
          </el-alert>
        </template>

        <!-- 应用选择 -->
        <el-form-item label="关联应用">
          <div style="display: flex; gap: 8px; width: 100%">
            <el-input v-model="form.platform_app_id" placeholder="应用ID" style="flex: 1" />
            <el-input v-model="form.platform_app_name" placeholder="应用名称（可选）" style="flex: 1" />
          </div>
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSave">
        {{ isEdit ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { projectsApi } from '@/api/projects'
import type { Project } from '@/api/projects'

const props = defineProps<{
  project?: Project | null
}>()

const emit = defineEmits<{
  saved: [project: Project]
}>()

const visible = defineModel<boolean>({ default: false })

const isEdit = computed(() => !!props.project?.id)

const form = reactive({
  name: '',
  description: '',
  platform_url: '',
  platform_tenant_id: '',
  platform_app_id: '',
  platform_app_name: '',
  platform_connected: false,
})

const connectMode = ref('login')
const loginForm = reactive({ username: '', password: '' })
const tokenForm = reactive({ token: '' })
const connecting = ref(false)
const saving = ref(false)

const canConnect = computed(() => {
  return form.platform_url && form.platform_tenant_id && loginForm.username && loginForm.password
})

// Watch for project changes to populate form
watch(() => props.project, (p) => {
  if (p) {
    form.name = p.name || ''
    form.description = p.description || ''
    form.platform_url = p.platform_url || ''
    form.platform_tenant_id = p.platform_tenant_id || ''
    form.platform_app_id = p.platform_app_id || ''
    form.platform_app_name = p.platform_app_name || ''
    form.platform_connected = p.platform_connected || false
    loginForm.username = p.platform_username || ''
    loginForm.password = ''
    tokenForm.token = ''
  } else {
    form.name = ''
    form.description = ''
    form.platform_url = ''
    form.platform_tenant_id = ''
    form.platform_app_id = ''
    form.platform_app_name = ''
    form.platform_connected = false
    loginForm.username = ''
    loginForm.password = ''
    tokenForm.token = ''
  }
}, { immediate: true })

async function handleConnect() {
  if (!props.project?.id) return
  connecting.value = true
  try {
    const updated = await projectsApi.connect(props.project.id, {
      username: loginForm.username,
      password: loginForm.password,
      base_url: form.platform_url,
      tenant_id: form.platform_tenant_id,
    })
    form.platform_connected = true
    ElMessage.success('平台连接成功')
    emit('saved', updated)
  } catch (e: any) {
    ElMessage.error(e.message || '连接失败')
  } finally {
    connecting.value = false
  }
}

async function handleSave() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  saving.value = true
  try {
    let result: Project
    if (isEdit.value && props.project?.id) {
      // Update existing project
      const updateData: Record<string, any> = {
        name: form.name,
        description: form.description,
        platform_url: form.platform_url,
        platform_tenant_id: form.platform_tenant_id,
        platform_app_id: form.platform_app_id,
        platform_app_name: form.platform_app_name,
      }
      // If token mode, include token
      if (connectMode.value === 'token' && tokenForm.token.trim()) {
        updateData.platform_token = tokenForm.token.trim()
      }
      if (loginForm.username) {
        updateData.platform_username = loginForm.username
      }
      result = await projectsApi.update(props.project.id, updateData)
    } else {
      // Create new project
      result = await projectsApi.create({
        name: form.name,
        description: form.description,
      })
    }
    ElMessage.success(isEdit.value ? '项目已保存' : '项目已创建')
    emit('saved', result)
    visible.value = false
  } catch (e: any) {
    ElMessage.error(e.message || '操作失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.project-settings-modal :deep(.el-dialog) {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
}
.project-settings-modal :deep(.el-dialog__header) {
  border-bottom: 1px solid #2a2a2a;
}
.project-settings-modal :deep(.el-dialog__title) {
  color: #e0e0e0;
}
.project-settings-modal :deep(.el-form-item__label) {
  color: #aaa;
}
.project-settings-modal :deep(.el-divider__text) {
  color: #888;
  background: #1a1a1a;
}
</style>

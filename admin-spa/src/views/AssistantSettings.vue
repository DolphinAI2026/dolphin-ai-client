<template>
  <div class="page assistant-page">
    <div class="page-header">
      <div>
        <h1>得小帆</h1>
        <p>配置得小帆 Dolphin 嵌入式助手，启用后前台工作台会加载右下角浮窗。</p>
      </div>
      <div class="page-actions">
        <el-button :loading="loading" @click="loadSettings">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
        <el-button type="primary" class="primary-button" :loading="saving" @click="saveSettings">
          <el-icon><Check /></el-icon>
          保存配置
        </el-button>
      </div>
    </div>

    <section class="settings-panel" v-loading="loading">
      <div class="panel-head">
        <div>
          <strong>得小帆</strong>
          <span>{{ statusText }}</span>
        </div>
        <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
      </div>

      <el-form class="assistant-form" label-position="top">
        <el-form-item label="Dolphin 服务地址" required>
          <el-input v-model="form.server_url" placeholder="https://dolphin-trial.definesys.cn" />
          <div class="field-help">用于加载 Dolphin embed SDK，保存时会自动去掉末尾斜杠。</div>
        </el-form-item>

        <el-form-item label="Agent Code" required>
          <el-input v-model="form.agent_code" placeholder="填写得小帆发布后的 Agent Code" />
          <div class="field-help">启用得小帆前必须填写。停用状态下可先保存为空。</div>
        </el-form-item>

        <el-form-item label="aPaaS 租户ID" required>
          <el-input v-model="form.apaas_tenant_id" placeholder="填写固定的 aPaaS 租户ID" />
          <div class="field-help">得小帆初始化时固定使用这个租户ID，不再使用当前 Builder 登录态里的租户ID。</div>
        </el-form-item>

        <el-form-item label="浮窗按钮文案">
          <el-input v-model="form.button_text" placeholder="得小帆" maxlength="80" show-word-limit />
        </el-form-item>
      </el-form>

      <div class="settings-footer">
        <div class="save-note">
          <span class="status-dot" :class="{ active: form.enabled && isConfigured }" />
          {{ footerText }}
        </div>
        <el-button type="primary" class="primary-button" :loading="saving" @click="saveSettings">保存配置</el-button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Refresh } from '@element-plus/icons-vue'
import { apiGet, apiPut } from '@/api/client'

interface DolphinAssistantSetting {
  tenant_id?: number
  enabled: boolean
  server_url: string
  agent_code: string
  apaas_tenant_id: string
  button_text: string
  configured?: boolean
  updated_at?: string | null
}

const loading = ref(false)
const saving = ref(false)

const form = reactive<DolphinAssistantSetting>({
  enabled: false,
  server_url: 'https://dolphin-trial.definesys.cn',
  agent_code: '',
  apaas_tenant_id: '',
  button_text: '得小帆',
})

const isConfigured = computed(() => !!form.agent_code.trim() && !!form.apaas_tenant_id.trim())
const statusText = computed(() => {
  if (form.enabled && isConfigured.value) return '已启用，刷新前台页面后加载浮窗'
  if (form.enabled) return '已启用，但配置还没填完整'
  return '当前停用，前台不会加载浮窗'
})
const footerText = computed(() => {
  if (form.enabled && isConfigured.value) return '保存后刷新前台页面生效'
  if (form.enabled) return '启用前请补齐 Agent Code 和 aPaaS 租户ID'
  return '停用后保存，前台刷新会移除浮窗'
})

function errorMessage(error: unknown, fallback: string) {
  const err = error as { response?: { data?: { detail?: string } }; message?: string }
  return err?.response?.data?.detail || err?.message || fallback
}

function applySetting(data: DolphinAssistantSetting) {
  form.enabled = !!data.enabled
  form.server_url = data.server_url || 'https://dolphin-trial.definesys.cn'
  form.agent_code = data.agent_code || ''
  form.apaas_tenant_id = data.apaas_tenant_id || ''
  form.button_text = !data.button_text || data.button_text === '问题助手' ? '得小帆' : data.button_text
}

async function loadSettings() {
  loading.value = true
  try {
    const data = await apiGet<DolphinAssistantSetting>('/assistant-settings/dolphin')
    applySetting(data)
  } catch (error) {
    ElMessage.error(errorMessage(error, '加载得小帆配置失败'))
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  const serverUrl = form.server_url.trim()
  if (!serverUrl) {
    ElMessage.warning('请填写 Dolphin 服务地址')
    return
  }
  if (!/^https?:\/\//i.test(serverUrl)) {
    ElMessage.warning('Dolphin 服务地址必须以 http:// 或 https:// 开头')
    return
  }
  if (form.enabled && !form.agent_code.trim()) {
    ElMessage.warning('启用得小帆前请填写 Agent Code')
    return
  }
  if (form.enabled && !form.apaas_tenant_id.trim()) {
    ElMessage.warning('启用得小帆前请填写 aPaaS 租户ID')
    return
  }

  saving.value = true
  try {
    const data = await apiPut<DolphinAssistantSetting>('/assistant-settings/dolphin', {
      enabled: form.enabled,
      server_url: serverUrl,
      agent_code: form.agent_code.trim(),
      apaas_tenant_id: form.apaas_tenant_id.trim(),
      button_text: form.button_text.trim() || '得小帆',
    })
    applySetting(data)
    ElMessage.success('得小帆配置已保存')
  } catch (error) {
    ElMessage.error(errorMessage(error, '保存得小帆配置失败'))
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.assistant-page {
  color: var(--text);
  font-family: var(--font-sans);
}

.primary-button {
  font-weight: var(--fw-medium, 500);
}

.settings-panel {
  overflow: hidden;
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-bottom: 1px solid var(--line);
}

.assistant-form {
  max-width: 760px;
  padding: 16px 18px 20px;
}

.field-help {
  margin-top: 6px;
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.5;
}

.settings-footer {
  min-height: 70px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px 18px;
  border-top: 1px solid var(--line);
  background: var(--surface-2);
}

.save-note {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-2);
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--warn);
}

.status-dot.active {
  background: var(--ok);
}

@media (max-width: 900px) {
  .settings-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>

<template>
  <div class="design-preview" v-loading="loading">
    <div v-if="error" class="error-banner">
      <el-alert :title="error" type="error" :closable="false" show-icon />
    </div>

    <template v-else-if="data">
      <!-- ── 头 ──────────────────────────────────── -->
      <div class="header">
        <div>
          <h1>{{ appName || '未命名应用' }}</h1>
          <div class="meta">
            <span>应用编码 <code>{{ appCode || '—' }}</code></span>
            <span v-if="appDesc">说明 {{ appDesc }}</span>
            <span>设计文档 <code>{{ data.draft_id }}</code></span>
            <span>状态 <el-tag size="small" :type="statusTagType">{{ data.status }}</el-tag></span>
          </div>
        </div>
        <div class="actions">
          <template v-if="data.status === 'active'">
            <el-input v-model="envInput" placeholder="环境别名 如 baogong" size="small" style="width: 180px; margin-right: 8px" />
            <el-button type="primary" :loading="promoting" @click="onPromote">✓ 确认创建</el-button>
          </template>
          <template v-else-if="data.status === 'promoted' && data.admin_url">
            <el-link :href="data.admin_url" target="_blank" type="primary">打开 aPaaS 后台 →</el-link>
          </template>
        </div>
      </div>

      <!-- ── Tabs ─────────────────────────────────── -->
      <el-tabs v-model="tab" class="tabs">
        <el-tab-pane label="业务流程" name="business">
          <BusinessFlowView :spec="data.spec" />
        </el-tab-pane>
        <el-tab-pane label="表单线框图" name="wireframe">
          <WireframeView :spec="data.spec" />
        </el-tab-pane>
        <el-tab-pane label="流程图/审批流" name="process">
          <ProcessFlowView :spec="data.spec" />
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiGet, apiPost } from '@/api/client'
import BusinessFlowView from '@/components/preview/BusinessFlowView.vue'
import WireframeView from '@/components/preview/WireframeView.vue'
import ProcessFlowView from '@/components/preview/ProcessFlowView.vue'

const route = useRoute()
const draftId = computed(() => String(route.params.draftId))

const loading = ref(true)
const promoting = ref(false)
const error = ref('')
const data = ref<any>(null)
const tab = ref('business')
const envInput = ref('baogong')

const appName = computed(() => data.value?.spec?.appName || data.value?.spec?.app_name || '')
const appCode = computed(() => data.value?.spec?.appCode || data.value?.spec?.app_code || '')
const appDesc = computed(() => data.value?.spec?.appDesc || data.value?.spec?.app_desc || '')
const statusTagType = computed(() => {
  const s = data.value?.status
  if (s === 'promoted' || s === 'applied') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'superseded') return 'info'
  return 'warning'
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiGet(`/design-drafts/${draftId.value}/spec`)
  } catch (e: any) {
    error.value = e?.response?.data?.detail?.errors?.[0]?.msg || e?.message || '加载设计文档失败'
  } finally {
    loading.value = false
  }
}

async function onPromote() {
  if (!envInput.value.trim()) {
    ElMessage.warning('请填写环境别名')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认把这份设计部署到环境 "${envInput.value}"？此操作会真实创建 aPaaS 应用。`,
      '确认创建',
      { type: 'warning' },
    )
  } catch {
    return
  }
  promoting.value = true
  try {
    const res = await apiPost(`/design-drafts/${draftId.value}/promote`, { env: envInput.value })
    if (res?.ok) {
      ElMessage.success(`应用已创建：${res.admin_url || ''}`)
      await load()
    } else {
      ElMessage.error(res?.errors?.[0]?.msg || res?.summary || '部署失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.errors?.[0]?.msg || e?.message || '部署失败')
  } finally {
    promoting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
/* v3 token 化 · 2026-05-20 — visual refresh only. template/script untouched. */
.design-preview {
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
}
.error-banner {
  padding: 24px 40px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 20px 40px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
.header h1 {
  margin: 0 0 8px;
  font-size: 22px;
  line-height: 1.25;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.01em;
  color: var(--text);
}
.header .meta {
  color: var(--text-3);
  font-size: 13px;
}
.header .meta span {
  margin-right: 24px;
}
.header .meta code {
  background: var(--surface-2);
  padding: 1px 6px;
  border-radius: var(--r-1, 4px);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11.5px;
  color: var(--text-2);
}
.actions {
  display: flex;
  align-items: center;
}
.tabs {
  padding: 0 40px;
}
.tabs :deep(.el-tabs__nav-wrap) {
  background: var(--surface);
}
.tabs :deep(.el-tabs__content) {
  padding: 20px 0;
}
</style>

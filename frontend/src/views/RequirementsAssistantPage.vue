<template>
  <WorkbenchShell>
    <div class="ra-page">
      <header class="ra-header">
        <div class="ra-title">
          <span class="ra-title-icon">💬</span>
          <span>AI 需求分析</span>
        </div>
        <div class="ra-subtitle">
          描述你的搭建需求，或拖入材料（PDF / Word / Excel / 截图），AI 会整合成可被 Builder 流水线直接解析的标准设计文档。
        </div>
      </header>

      <div v-if="loading" class="ra-loading">
        <span class="spinner">⟳</span>
        <span>加载 AI 需求分析助手...</span>
      </div>

      <div v-else-if="!agentCode" class="ra-not-configured">
        <div class="ra-not-configured-icon">⚙️</div>
        <div class="ra-not-configured-title">尚未配置 AI 需求分析助手</div>
        <div class="ra-not-configured-hint">
          请联系管理员在 backend <code>.env</code> 中设置
          <code>DOLPHIN_REQUIREMENTS_AGENT_CODE</code> 后重启后端服务。
        </div>
      </div>

      <div v-else class="ra-embed-wrap">
        <DolphinAgentEmbed :agent-code="agentCode" title="AI 需求分析助手" />
      </div>
    </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import DolphinAgentEmbed from '@/components/DolphinAgentEmbed.vue'
import request from '@/utils/request'

const loading = ref(true)
const agentCode = ref('')

interface DolphinConfig {
  requirements_agent_code?: string
}

onMounted(async () => {
  try {
    const cfg = await request.get<unknown, DolphinConfig>('/dolphin/config')
    agentCode.value = cfg?.requirements_agent_code || ''
  } catch (e) {
    console.warn('[RequirementsAssistant] /dolphin/config failed', e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.ra-page {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: var(--t-bg, #fff);
}
.ra-header {
  padding: 18px 24px 12px;
  border-bottom: 1px solid var(--t-border-subtle);
  flex-shrink: 0;
}
.ra-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 600;
  color: var(--t-text-primary);
}
.ra-title-icon {
  font-size: 18px;
}
.ra-subtitle {
  margin-top: 6px;
  font-size: 13px;
  color: var(--t-text-secondary);
  line-height: 1.55;
}
.ra-embed-wrap {
  flex: 1;
  min-height: 0;
}
.ra-loading,
.ra-not-configured {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--t-text-muted);
  font-size: 14px;
}
.ra-not-configured-icon {
  font-size: 36px;
  opacity: 0.7;
}
.ra-not-configured-title {
  font-size: 15px;
  color: var(--t-text-primary);
  font-weight: 600;
}
.ra-not-configured-hint {
  font-size: 13px;
  text-align: center;
  max-width: 480px;
  line-height: 1.6;
}
.ra-not-configured-hint code {
  background: var(--t-bg-input);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.spinner {
  display: inline-block;
  animation: spin 1s linear infinite;
  font-size: 16px;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>

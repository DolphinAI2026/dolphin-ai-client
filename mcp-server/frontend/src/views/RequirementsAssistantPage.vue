<template>
  <WorkbenchShell>
    <div class="ra-page">
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

      <DolphinAgentEmbed
        v-else
        class="ra-chat-fullwidth"
        :agent-code="agentCode"
        title="AI 需求分析助手"
      />
    </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
/**
 * AI 需求分析页 — 嵌入 dolphin 需求分析助手对话窗口。
 *
 * 设计：纯 iframe 容器，不再做轮询 / md 抽取 / 底部 action bar。
 * agent 写完 md 后会调 mcp_server.submit_design_doc 工具，把 md push 到
 * 后端 cache 同时返回一条 deeplink；agent 把 deeplink 用 markdown 链接格式
 * 贴在 chat 里，用户点击在新 tab 进 ChatPage（/chat?from=requirements），
 * ChatPage 会自动从 cache 拉 md 弹 ChooseAppTargetDialog。
 *
 * 历史：曾在底部加 56px action bar 显示「自动同步 + 文件名 + 自检 + → Builder」，
 * 配合 5s 轮询 dolphin chat history 抽 markdown 块。dolphin MCP 工具关联修
 * 好后这条拉模式 workaround 整段删除。如需排查可看 git blame ra-action-bar。
 */
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
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Maps v2 --t-* tokens to v3 surface/text/r tokens; preserves spinner anim. */
.ra-page {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: var(--bg);
}
.ra-loading,
.ra-not-configured {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s-3, 12px);
  color: var(--text-3);
  font-size: var(--t-body, 14px);
}
.ra-not-configured-icon {
  font-size: 36px;
  opacity: 0.7;
}
.ra-not-configured-title {
  font-size: 15px;
  color: var(--text);
  font-weight: var(--fw-semibold, 600);
}
.ra-not-configured-hint {
  font-size: 13px;
  text-align: center;
  max-width: 480px;
  line-height: 1.6;
}
.ra-not-configured-hint code {
  background: var(--surface-3);
  padding: 1px 6px;
  border-radius: var(--r-1, 4px);
  font-size: var(--t-small, 12.5px);
  font-family: var(--font-mono);
  color: var(--text-2);
}
.spinner {
  display: inline-block;
  font-size: 24px;
  color: var(--brand);
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.ra-chat-fullwidth {
  flex: 1;
  min-height: 0;
}
</style>

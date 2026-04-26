<template>
  <div class="chat-panel">
    <PromoteApproveApplyCard
      v-if="store.effectiveMode === 'simple' && store.state?.current_draft && store.state?.application"
      :draft-spec-id="store.state.current_draft.id"
      :application-id="store.state.application.id"
      @done="onProposalDone"
    />
    <iframe
      v-if="iframeSrc"
      :src="iframeSrc"
      class="chat-iframe"
      sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
    />
    <div v-else class="empty">
      <p class="muted">未指定应用上下文</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import PromoteApproveApplyCard from './PromoteApproveApplyCard.vue'

const store = useWorkspaceStore()

function onProposalDone(_id: string) {
  // store.refresh() 已在 PromoteApproveApplyCard 内部调用
}

// 复用 ChatPage 既有的 deploy_app_id 解析路径：自动找应用关联的活跃 conversation
// 包括：既有 SPEC 进度 / 部署进度 / 5-stage 仍可见（embed 模式仅隐顶栏 / breadcrumb）
const iframeSrc = computed(() => {
  const appId = store.application?.id
  if (!appId) return ''
  // 用 BASE_URL 兼容 vite base = '/ai-builder/' 的部署
  return `${import.meta.env.BASE_URL}chat?deploy_app_id=${appId}&embed=true`
})
</script>

<style scoped>
.chat-panel { height: 100%; display: flex; flex-direction: column; }
.empty { padding: 32px; text-align: center; }
.empty p { color: var(--fg-muted); margin-bottom: 16px; }
.chat-iframe { flex: 1; border: 0; width: 100%; }
</style>

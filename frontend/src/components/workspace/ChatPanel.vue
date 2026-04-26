<template>
  <div class="chat-panel">
    <PromoteApproveApplyCard
      v-if="store.effectiveMode === 'simple' && store.state?.current_draft && store.state?.application"
      :draft-spec-id="store.state.current_draft.id"
      :application-id="store.state.application.id"
      @done="onProposalDone"
    />
    <div class="cta">
      <p class="muted">完整 Chat 工作台体验</p>
      <button class="builder-btn builder-btn-primary big" type="button" @click="openChat">
        打开 Chat 工作台 ↗
      </button>
      <p class="hint muted small">
        · 跟 AI 对话生成 / 修改 SPEC<br />
        · 上传文档自动解析<br />
        · 5 阶段流程：理解需求 → SPEC → 配置 → 自开发 → 部署
      </p>
      <p class="meta muted small" v-if="store.state?.current_draft || store.state?.canonical">
        当前 SPEC：v{{ store.state?.canonical?.version ?? store.state?.current_draft?.version }}
        · 完整度
        {{ store.state?.current_draft?.completeness_confirmed ?? 0 }}/{{
          store.state?.current_draft?.completeness_total ?? 0
        }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useWorkspaceStore } from '@/stores/workspace'
import PromoteApproveApplyCard from './PromoteApproveApplyCard.vue'

const store = useWorkspaceStore()

function onProposalDone(_id: string) {
  // store.refresh() 已在 PromoteApproveApplyCard 内部调用
}

function openChat() {
  const appId = store.application?.id
  if (!appId) return
  // 同窗口打开（保留浏览器后退到 WorkspaceShell）
  window.location.href = `${import.meta.env.BASE_URL}chat?deploy_app_id=${appId}`
}
</script>

<style scoped>
.chat-panel { height: 100%; display: flex; flex-direction: column; gap: 16px; }
.cta { padding: 24px 16px; text-align: center; display: flex; flex-direction: column; gap: 12px; align-items: center; }
.cta .big { padding: 12px 24px; font-size: 14px; }
.muted { color: var(--fg-muted); }
.small { font-size: 12px; }
.hint { line-height: 1.7; text-align: left; max-width: 240px; }
.meta { padding: 8px 12px; background: var(--bg-inset); border-radius: 6px; }
</style>

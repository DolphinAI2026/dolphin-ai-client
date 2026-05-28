<template>
  <BuilderFrame :breadcrumbs="[{ label: 'AI Coding' }, { label: '新建' }]">
    <div class="ace">
      <h1 class="ace-title">想做个什么应用？</h1>
      <p class="ace-sub">一句话描述你的想法，AI 帮你从零搭起来。</p>
      <textarea
        v-model="idea" class="ace-input" rows="4" :disabled="creating"
        placeholder="例如：做一个报销系统，员工提交报销单、主管审批、财务打款，带统计看板"
        @keydown.meta.enter="onCreate" @keydown.ctrl.enter="onCreate"
      ></textarea>
      <div class="ace-actions">
        <button class="ace-go" :disabled="!idea.trim() || creating" @click="onCreate">
          {{ creating ? '创建中…' : '开始构建 →' }}
        </button>
        <span class="ace-hint">⌘/Ctrl + Enter</span>
      </div>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { onlineCodingApi } from '@/api/onlineCoding'

const router = useRouter()
const idea = ref('')
const creating = ref(false)

async function onCreate() {
  const task = idea.value.trim()
  if (!task || creating.value) return
  creating.value = true
  try {
    const ws = await onlineCodingApi.createWorkspace({ task })
    // 种首条 prompt：VibeChatPanel 挂载时自动读 sessionStorage 并发送
    sessionStorage.setItem(`vibe_pending_prompt_${ws.id}`, task)
    router.push(`/ai-coding/${ws.id}`)
  } catch (e: any) {
    ElMessage.error('创建失败：' + (e?.message || e))
    creating.value = false
  }
}
</script>

<style scoped>
.ace { max-width: 680px; margin: 8vh auto 0; padding: 0 24px; display: flex; flex-direction: column; }
.ace-title { font-size: 28px; font-weight: 700; color: var(--text-2); margin: 0 0 8px; }
.ace-sub { color: var(--text-3); margin: 0 0 24px; }
.ace-input { width: 100%; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; font-size: 15px; line-height: 1.6; background: var(--surface-3); color: var(--text-2); resize: vertical; font-family: inherit; }
.ace-input:focus { outline: none; border-color: var(--brand); }
.ace-actions { display: flex; align-items: center; gap: 12px; margin-top: 16px; }
.ace-go { border: 0; background: var(--brand); color: #fff; border-radius: 10px; padding: 10px 22px; font-size: 15px; font-weight: 600; cursor: pointer; }
.ace-go:disabled { opacity: .5; cursor: default; }
.ace-hint { color: var(--text-4); font-size: 12px; }
</style>

<template>
  <section v-if="show" class="paa-card">
    <div class="paa-header">
      <span class="paa-icon">🤖</span>
      <h4>AI 准备好一次变更</h4>
    </div>
    <div class="paa-meta">
      <p>{{ summary }}</p>
      <p class="muted small">影响：{{ reversibilityLabel }}</p>
    </div>
    <div class="paa-actions">
      <button class="builder-btn builder-btn-primary" :disabled="working" @click="onApply">
        {{ working ? '执行中...' : 'Promote & Approve & Apply ✓' }}
      </button>
      <button class="builder-btn" :disabled="working" @click="onPromoteOnly">先 Promote</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { proposalsApi } from '@/api/proposals'
import { useWorkspaceStore } from '@/stores/workspace'

const props = defineProps<{
  draftSpecId: string | null
  applicationId: number
  reversibilitySummary?: { red: number; yellow: number; green: number }
}>()

const emit = defineEmits<{
  done: [proposalId: string]
}>()

const store = useWorkspaceStore()
const working = ref(false)
const error = ref('')

const show = computed(() => !!props.draftSpecId)
const summary = computed(() => `Spec ${props.draftSpecId?.slice(0, 12)} 的最新变更`)
const reversibilityLabel = computed(() => {
  const r = props.reversibilitySummary
  if (!r) return '尚未分析'
  if (r.red > 0) return `${r.red} 个不可逆 + ${r.yellow} 部分可逆 + ${r.green} 可逆`
  if (r.yellow > 0) return `${r.yellow} 部分可逆 + ${r.green} 可逆 — 安全`
  return `全部 ${r.green} 个变更可逆 — 完全安全`
})

async function onPromoteOnly() {
  if (!props.draftSpecId) return
  working.value = true
  error.value = ''
  try {
    const res = await proposalsApi.promote(props.applicationId, {
      title: `AI 编辑：${new Date().toLocaleString()}`,
      draft_spec_id: props.draftSpecId,
    })
    emit('done', res.id)
    await store.refresh()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'promote 失败'
  } finally {
    working.value = false
  }
}

async function onApply() {
  if (!props.draftSpecId) return
  working.value = true
  error.value = ''
  try {
    // 1. promote
    const promoteRes = await proposalsApi.promote(props.applicationId, {
      title: `AI 编辑（in-chat 自动）：${new Date().toLocaleString()}`,
      draft_spec_id: props.draftSpecId,
    })
    if (promoteRes.status !== 'open') {
      throw new Error(`第一道门未通过：${JSON.stringify(promoteRes.validation_report)}`)
    }
    // 2. review approve（用当前用户身份）
    await proposalsApi.review(promoteRes.id, 'approve', 'in-chat 快捷批准 (Phase F simple mode)')
    // 3. apply（先尝试不带 confirm_irreversible）
    const applyRes = await proposalsApi.apply(promoteRes.id, false)
    if (applyRes.status === 'needs_confirmation') {
      // 弹不可逆 modal（v1 用 window.confirm 简化；正式版用 BaseDialog — backlog）
      const confirmed = window.confirm(
        '⚠ 此变更含不可逆操作，apply 后无法直接撤销。继续？',
      )
      if (!confirmed) {
        emit('done', promoteRes.id)
        await store.refresh()
        return
      }
      await proposalsApi.apply(promoteRes.id, true)
    }
    emit('done', promoteRes.id)
    await store.refresh()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'apply 失败'
  } finally {
    working.value = false
  }
}
</script>

<style scoped>
.paa-card { padding: 16px; border: 1px solid var(--brand); border-radius: 8px; background: var(--brand-soft); margin-bottom: 16px; }
.paa-header { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.paa-header h4 { margin: 0; color: var(--fg); }
.paa-icon { font-size: 18px; }
.paa-meta p { margin: 4px 0; color: var(--fg); font-size: 13px; }
.muted { color: var(--fg-muted); font-size: 11px; }
.small { font-size: 11px; }
.paa-actions { display: flex; gap: 8px; margin-top: 12px; }
.error { color: var(--t-danger); font-size: 12px; margin-top: 8px; }
</style>

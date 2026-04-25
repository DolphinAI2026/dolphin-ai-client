<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { DictSpec } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps<{ dict: DictSpec }>()
const spec = useSpecStore()

async function confirm() {
  try {
    await spec.updateItem('dict', props.dict.code, 'confirm')
    ElMessage.success(`已确认字典：${props.dict.name}`)
  } catch (e: unknown) {
    ElMessage.error(`确认失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismiss() {
  try { await ElMessageBox.confirm(`删除字典「${props.dict.name}」？`, '确认删除', { type: 'warning' }) }
  catch { return }
  try {
    await spec.updateItem('dict', props.dict.code, 'dismiss')
    ElMessage.success(`已删除字典：${props.dict.name}`)
  } catch (e: unknown) {
    ElMessage.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <article class="spec-card" :class="{ confirmed: dict.confirmed }">
    <header class="spec-card-header">
      <h4 class="spec-card-title">📚 {{ dict.name }} <span class="spec-card-code">{{ dict.code }}</span></h4>
    </header>
    <ul class="dict-options">
      <li v-for="opt in dict.options" :key="opt.code">
        <span class="opt-name">{{ opt.name }}</span>
        <span class="opt-code">{{ opt.code }}</span>
      </li>
    </ul>
    <footer class="spec-card-actions">
      <span v-if="dict.confirmed" class="spec-card-status">✓ 已确认</span>
      <template v-else>
        <button class="action-btn confirm" @click="confirm">✓ 确认</button>
        <button class="action-btn dismiss" @click="dismiss">✕ 删除</button>
      </template>
    </footer>
  </article>
</template>

<style scoped>
.spec-card { border: 1px solid var(--t-border-subtle); border-radius: var(--t-radius-md); padding: 12px 14px; background: var(--t-bg-panel); }
.spec-card.confirmed { border-color: var(--t-success); background: var(--t-success-subtle); }
.spec-card-header { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.spec-card-title { margin: 0; font-size: 14px; color: var(--t-text-primary); }
.spec-card-code { font-family: monospace; font-size: 12px; color: var(--t-text-muted); }
.dict-options { list-style: none; padding: 0; margin: 8px 0; display: flex; flex-wrap: wrap; gap: 6px; }
.dict-options li { background: var(--t-bg-input); padding: 3px 9px; border-radius: var(--t-radius-sm); font-size: 12px; display: inline-flex; gap: 6px; align-items: center; }
.opt-name { color: var(--t-text-primary); }
.opt-code { font-family: monospace; color: var(--t-text-muted); font-size: 11px; }
.spec-card-actions { display: flex; gap: 8px; margin-top: 8px; }
.action-btn { padding: 4px 10px; font-size: 12px; border: 1px solid var(--t-border-subtle); border-radius: var(--t-radius-sm); background: var(--t-bg-input); cursor: pointer; }
.action-btn.confirm:hover { background: var(--t-success-subtle); border-color: var(--t-success); color: var(--t-success); }
.action-btn.dismiss:hover { background: var(--t-danger-subtle); border-color: var(--t-danger); color: var(--t-danger); }
.spec-card-status { color: var(--t-success); font-size: 12px; font-weight: 600; }
</style>

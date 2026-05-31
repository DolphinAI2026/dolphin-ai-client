<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { DictSpec } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps<{ dict: DictSpec }>()
const spec = useSpecStore()

async function confirm() {
  try {
    await spec.updateItem('dict', props.dict.code, 'confirm')
    ElMessage.success(`已采纳字典：${props.dict.name}`)
  } catch (e: unknown) {
    ElMessage.error(`采纳失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismiss() {
  try { await ElMessageBox.confirm(`忽略字典「${props.dict.name}」？忽略后将不进入本轮生成草稿。`, '忽略字典', { type: 'warning' }) }
  catch { return }
  try {
    await spec.updateItem('dict', props.dict.code, 'dismiss')
    ElMessage.success(`已忽略字典：${props.dict.name}`)
  } catch (e: unknown) {
    ElMessage.error(`忽略失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <article class="spec-card" :class="{ confirmed: dict.confirmed }">
    <header class="spec-card-header">
      <h4 class="spec-card-title">{{ dict.name }} <span class="spec-card-code">{{ dict.code }}</span></h4>
    </header>
    <ul class="dict-options">
      <li v-for="opt in dict.options" :key="opt.code">
        <span class="opt-name">{{ opt.name }}</span>
        <span class="opt-code">{{ opt.code }}</span>
      </li>
    </ul>
    <footer class="spec-card-actions">
      <span v-if="dict.confirmed" class="spec-card-status">✓ 已采纳</span>
      <template v-else>
        <button class="action-btn confirm" @click="confirm">✓ 采纳</button>
        <button class="action-btn dismiss" @click="dismiss">忽略</button>
      </template>
    </footer>
  </article>
</template>

<style scoped>
.spec-card { border: 1px solid var(--t-border-subtle); border-radius: 12px; padding: 13px 15px; background: var(--t-bg-panel); }
.spec-card.confirmed { border-color: var(--t-border-strong); box-shadow: inset 3px 0 0 var(--t-success); }
.spec-card-header { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.spec-card-title { margin: 0; font-size: 14px; line-height: 1.35; color: var(--t-text-primary); }
.spec-card-code {
  font-family: monospace;
  font-size: 11px;
  color: var(--t-text-muted);
  background: var(--t-bg-input);
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  padding: 1px 6px;
}
.dict-options { list-style: none; padding: 0; margin: 8px 0; display: flex; flex-wrap: wrap; gap: 6px; }
.dict-options li {
  background: var(--t-bg-input);
  border: 1px solid var(--t-border-subtle);
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  display: inline-flex;
  gap: 6px;
  align-items: center;
}
.opt-name { color: var(--t-text-primary); }
.opt-code { font-family: monospace; color: var(--t-text-muted); font-size: 11px; }
.spec-card-actions { display: flex; gap: 6px; margin-top: 10px; align-items: center; }
.action-btn {
  height: 26px;
  padding: 0 9px;
  font-size: 12px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.action-btn.confirm:hover { background: var(--t-success-subtle); border-color: var(--t-success); color: var(--t-success); }
.action-btn.dismiss:hover { background: var(--t-danger-subtle); border-color: var(--t-danger); color: var(--t-danger); }
.spec-card-status {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 999px;
  background: var(--t-success-subtle);
  color: var(--t-success);
  font-size: 11px;
  font-weight: 700;
}
</style>

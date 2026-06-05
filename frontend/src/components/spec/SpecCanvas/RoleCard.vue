<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { Role } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '@/components/common/AppIcon.vue'

const props = defineProps<{ role: Role }>()
const spec = useSpecStore()

function scopeLabel(scope: string): string {
  return ({ ALL: '全部', DEPT: '本部门', DEPT_LOW: '部门及下级', SELF: '仅本人' } as Record<string, string>)[scope] || scope
}

async function confirm() {
  try {
    await spec.updateItem('role', props.role.code, 'confirm')
    ElMessage.success(`已采纳角色：${props.role.name}`)
  } catch (e: unknown) {
    ElMessage.error(`采纳失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismiss() {
  try {
    await ElMessageBox.confirm(
      `忽略角色「${props.role.name}」？忽略后将不进入本轮生成草稿。`,
      '忽略角色',
      { type: 'warning' }
    )
  } catch { return /* user cancelled */ }
  try {
    await spec.updateItem('role', props.role.code, 'dismiss')
    ElMessage.success(`已忽略角色：${props.role.name}`)
  } catch (e: unknown) {
    ElMessage.error(`忽略失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <article class="spec-card" :class="{ confirmed: role.confirmed }">
    <header class="spec-card-header">
      <h4 class="spec-card-title">{{ role.name }}</h4>
      <span class="spec-card-code">{{ role.code }}</span>
      <span class="spec-card-scope">数据范围：{{ scopeLabel(role.scope) }}</span>
    </header>
    <p v-if="role.description" class="spec-card-desc">{{ role.description }}</p>
    <footer class="spec-card-actions">
      <span v-if="role.confirmed" class="spec-card-status"><AppIcon name="check" :size="14" /> 已采纳</span>
      <template v-else>
        <button class="action-btn confirm" @click="confirm"><AppIcon name="check" :size="14" /> 采纳</button>
        <button class="action-btn dismiss" @click="dismiss">忽略</button>
      </template>
    </footer>
  </article>
</template>

<style scoped>
.spec-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: 12px;
  padding: 13px 15px;
  background: var(--t-bg-panel);
  transition: border-color 0.15s, background 0.15s;
}
.spec-card.confirmed {
  border-color: var(--t-border-strong);
  box-shadow: inset 3px 0 0 var(--t-success);
}
.spec-card-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
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
.spec-card-scope { font-size: 12px; color: var(--t-text-secondary); margin-left: auto; }
.spec-card-desc { margin: 8px 0 0; font-size: 13px; line-height: 1.55; color: var(--t-text-secondary); }
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

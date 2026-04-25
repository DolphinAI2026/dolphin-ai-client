<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { Role } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps<{ role: Role }>()
const spec = useSpecStore()

function scopeLabel(scope: string): string {
  return ({ ALL: '全部', DEPT: '本部门', DEPT_LOW: '部门及下级', SELF: '仅本人' } as Record<string, string>)[scope] || scope
}

async function confirm() {
  try {
    await spec.updateItem('role', props.role.code, 'confirm')
    ElMessage.success(`已确认角色：${props.role.name}`)
  } catch (e: unknown) {
    ElMessage.error(`确认失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismiss() {
  try {
    await ElMessageBox.confirm(
      `确定删除角色「${props.role.name}」？此操作不可撤销。`,
      '确认删除',
      { type: 'warning' }
    )
  } catch { return /* user cancelled */ }
  try {
    await spec.updateItem('role', props.role.code, 'dismiss')
    ElMessage.success(`已删除角色：${props.role.name}`)
  } catch (e: unknown) {
    ElMessage.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
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
      <span v-if="role.confirmed" class="spec-card-status">✓ 已确认</span>
      <template v-else>
        <button class="action-btn confirm" @click="confirm">✓ 确认</button>
        <button class="action-btn dismiss" @click="dismiss">✕ 删除</button>
      </template>
    </footer>
  </article>
</template>

<style scoped>
.spec-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-md);
  padding: 12px 14px;
  background: var(--t-bg-panel);
  transition: border-color 0.15s;
}
.spec-card.confirmed {
  border-color: var(--t-success);
  background: var(--t-success-subtle);
}
.spec-card-header { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.spec-card-title { margin: 0; font-size: 14px; color: var(--t-text-primary); }
.spec-card-code { font-family: monospace; font-size: 12px; color: var(--t-text-muted); }
.spec-card-scope { font-size: 12px; color: var(--t-text-secondary); margin-left: auto; }
.spec-card-desc { margin: 6px 0; font-size: 13px; color: var(--t-text-secondary); }
.spec-card-actions { display: flex; gap: 8px; margin-top: 8px; }
.action-btn {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-sm);
  background: var(--t-bg-input);
  cursor: pointer;
}
.action-btn.confirm:hover { background: var(--t-success-subtle); border-color: var(--t-success); color: var(--t-success); }
.action-btn.dismiss:hover { background: var(--t-danger-subtle); border-color: var(--t-danger); color: var(--t-danger); }
.spec-card-status { color: var(--t-success); font-size: 12px; font-weight: 600; }
</style>

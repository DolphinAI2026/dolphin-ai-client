<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { PermissionSpec } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps<{ permission: PermissionSpec }>()
const spec = useSpecStore()

async function confirm() {
  try {
    await spec.updateItem('permission', props.permission.object_code, 'confirm')
    ElMessage.success('权限已确认')
  } catch (e: unknown) { ElMessage.error(`确认失败：${e instanceof Error ? e.message : String(e)}`) }
}

async function dismiss() {
  try { await ElMessageBox.confirm(`删除「${props.permission.object_code}」的权限规则？`, '确认删除', { type: 'warning' }) } catch { return }
  try {
    await spec.updateItem('permission', props.permission.object_code, 'dismiss')
    ElMessage.success('权限已删除')
  } catch (e: unknown) { ElMessage.error(`删除失败：${e instanceof Error ? e.message : String(e)}`) }
}

function opLabel(op: string): string {
  return ({ all: '全部', add: '新增', edit: '编辑', delete: '删除', view: '查看' } as Record<string, string>)[op] || op
}
function dataLabel(d: string): string {
  return ({ ALL: '全部数据', SELF: '仅本人', DEPT: '本部门', DEPT_LOW: '部门及下级' } as Record<string, string>)[d] || d
}
</script>

<template>
  <article class="spec-card" :class="{ confirmed: permission.confirmed }">
    <header class="spec-card-header">
      <h4 class="spec-card-title">🔒 {{ permission.object_code }} 的权限</h4>
    </header>
    <table class="perm-rules">
      <thead><tr><th>角色</th><th>操作</th><th>数据范围</th></tr></thead>
      <tbody>
        <tr v-for="(rule, i) in permission.rules" :key="i">
          <td><code>{{ rule.role }}</code></td>
          <td>{{ opLabel(rule.op) }}</td>
          <td>{{ dataLabel(rule.data) }}</td>
        </tr>
      </tbody>
    </table>
    <footer class="spec-card-actions">
      <span v-if="permission.confirmed" class="spec-card-status">✓ 已确认</span>
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
.spec-card-header { display: flex; align-items: baseline; gap: 8px; }
.spec-card-title { margin: 0; font-size: 14px; color: var(--t-text-primary); }
.perm-rules { width: 100%; margin: 8px 0; border-collapse: collapse; font-size: 12px; }
.perm-rules th, .perm-rules td { padding: 4px 8px; border-bottom: 1px solid var(--t-border-subtle); text-align: left; }
.perm-rules th { color: var(--t-text-muted); font-weight: 500; }
.perm-rules td code { font-family: monospace; background: var(--t-bg-input); padding: 1px 5px; border-radius: 3px; }
.spec-card-actions { display: flex; gap: 8px; margin-top: 8px; }
.action-btn { padding: 4px 10px; font-size: 12px; border: 1px solid var(--t-border-subtle); border-radius: var(--t-radius-sm); background: var(--t-bg-input); cursor: pointer; }
.action-btn.confirm:hover { background: var(--t-success-subtle); border-color: var(--t-success); color: var(--t-success); }
.action-btn.dismiss:hover { background: var(--t-danger-subtle); border-color: var(--t-danger); color: var(--t-danger); }
.spec-card-status { color: var(--t-success); font-size: 12px; font-weight: 600; }
</style>

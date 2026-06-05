<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { PermissionSpec } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '@/components/common/AppIcon.vue'

const props = defineProps<{ permission: PermissionSpec }>()
const spec = useSpecStore()

async function confirm() {
  try {
    await spec.updateItem('permission', props.permission.object_code, 'confirm')
    ElMessage.success('权限已采纳')
  } catch (e: unknown) { ElMessage.error(`采纳失败：${e instanceof Error ? e.message : String(e)}`) }
}

async function dismiss() {
  try { await ElMessageBox.confirm(`忽略「${props.permission.object_code}」的权限规则？忽略后将不进入本轮生成草稿。`, '忽略权限规则', { type: 'warning' }) } catch { return }
  try {
    await spec.updateItem('permission', props.permission.object_code, 'dismiss')
    ElMessage.success('权限已忽略')
  } catch (e: unknown) { ElMessage.error(`忽略失败：${e instanceof Error ? e.message : String(e)}`) }
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
      <h4 class="spec-card-title">{{ permission.object_code }} 的权限</h4>
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
      <span v-if="permission.confirmed" class="spec-card-status"><AppIcon name="check" :size="14" /> 已采纳</span>
      <template v-else>
        <button class="action-btn confirm" @click="confirm"><AppIcon name="check" :size="14" /> 采纳</button>
        <button class="action-btn dismiss" @click="dismiss">忽略</button>
      </template>
    </footer>
  </article>
</template>

<style scoped>
.spec-card { border: 1px solid var(--t-border-subtle); border-radius: 12px; padding: 13px 15px; background: var(--t-bg-panel); }
.spec-card.confirmed { border-color: var(--t-border-strong); box-shadow: inset 3px 0 0 var(--t-success); }
.spec-card-header { display: flex; align-items: baseline; gap: 8px; }
.spec-card-title { margin: 0; font-size: 14px; line-height: 1.35; color: var(--t-text-primary); }
.perm-rules {
  width: 100%;
  margin: 10px 0 0;
  border-collapse: separate;
  border-spacing: 0;
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
  overflow: hidden;
  font-size: 12px;
}
.perm-rules th, .perm-rules td { padding: 7px 9px; border-bottom: 1px solid var(--t-border-subtle); text-align: left; }
.perm-rules tbody tr:last-child td { border-bottom: 0; }
.perm-rules th { color: var(--t-text-muted); font-weight: 700; background: var(--t-bg-input); }
.perm-rules td { color: var(--t-text-secondary); }
.perm-rules td code {
  font-family: monospace;
  background: var(--t-bg-input);
  border: 1px solid var(--t-border-subtle);
  padding: 1px 6px;
  border-radius: 6px;
  color: var(--t-text-primary);
}
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

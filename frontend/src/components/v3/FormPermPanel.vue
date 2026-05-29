<!-- FormPermPanel.vue — 表单级权限矩阵 (设计器第5子tab「权限」).
     角色 × 查看/编辑/删除/新增/导入 + 数据范围。读真 apaas:
     GET /applications/{appId}/forms/{formId}/permissions(list_apaas_form_permissions 归一)。
     2026-05-29 Phase A: 只读渲染。edit/保存(写回 set_apaas_form_permissions)= Phase B。
     视觉对齐 LogsPanel 表格 + 复用 states/ 组件 + BaseBadge/BaseTag,全 token。 -->
<template>
  <section class="fpp" aria-label="表单权限">
    <header class="fpp-head">
      <div class="fpp-head-meta">
        <h1 class="fpp-title">表单权限</h1>
        <p v-if="!loading && !error" class="fpp-stat">
          <b>{{ dataRoles.length }}</b> 角色 · {{ menuName || formId }}
        </p>
        <p v-else-if="loading" class="fpp-stat">加载中…</p>
      </div>
      <button class="fpp-btn fpp-btn-ghost" :disabled="loading" @click="load">
        <span aria-hidden="true">⟲</span> 刷新
      </button>
    </header>

    <div class="fpp-banner">
      <span aria-hidden="true">✨</span>
      业务视角预览 — 这个表单的<strong>角色权限</strong>(查看/编辑/删除/新增/导入 + 数据范围)。当前只读，编辑能力下一步接入。
    </div>

    <div class="fpp-body">
      <SkeletonCard v-if="loading" :lines="5" />
      <ErrorCard
        v-else-if="error"
        level="err"
        title="加载表单权限失败"
        :message="error"
        :actions="[{ label: '重试', onClick: load }]"
      />
      <EmptyState
        v-else-if="!dataRoles.length"
        title="暂无角色"
        desc="先在「权限 → 角色」创建角色 / 部署应用，再回这里配这个表单的权限"
      >
        <template #icon>🔑</template>
      </EmptyState>
      <div v-else class="fpp-table-wrap">
        <table class="fpp-table">
          <thead>
            <tr>
              <th class="fpp-col-role">角色</th>
              <th v-for="col in COLS" :key="col.key">{{ col.label }}</th>
              <th class="fpp-col-range">数据范围</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="role in dataRoles" :key="role.role_id">
              <td class="fpp-col-role">
                <span class="fpp-role-name">{{ role.role_name }}</span>
                <BaseTag v-if="role.is_all_user" tone="brand">默认</BaseTag>
              </td>
              <td v-for="col in COLS" :key="col.key" class="fpp-cell">
                <span v-if="cellOf(role.role_id)[col.key]" class="fpp-on" title="有权限">✓</span>
                <span v-else class="fpp-off" title="无权限">—</span>
              </td>
              <td class="fpp-col-range">
                <BaseBadge
                  v-if="cellOf(role.role_id).view || cellOf(role.role_id).edit"
                  :variant="rangeVariant(cellOf(role.role_id).range)"
                  size="sm"
                >{{ rangeLabel(cellOf(role.role_id).range) }}</BaseBadge>
                <span v-else class="fpp-off">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import request from '@/utils/request'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorCard from '@/components/states/ErrorCard.vue'
import BaseBadge from '@/components/BaseBadge.vue'
import BaseTag from '@/components/BaseTag.vue'

interface PermRole { role_id: string; role_name: string; is_all_user?: boolean }
interface PermCell { view: boolean; edit: boolean; delete: boolean; add: boolean; import: boolean; range: string | null }

const props = defineProps<{
  appId: number
  apaasAppId?: string
  envId?: number
  formId: string
  menuName?: string
}>()

const COLS = [
  { key: 'view', label: '查看' },
  { key: 'edit', label: '编辑' },
  { key: 'delete', label: '删除' },
  { key: 'add', label: '新增' },
  { key: 'import', label: '导入' },
] as const

const loading = ref(false)
const error = ref('')
const dataRoles = ref<PermRole[]>([])
const matrix = ref<Record<string, PermCell>>({})

const EMPTY_CELL: PermCell = { view: false, edit: false, delete: false, add: false, import: false, range: null }
function cellOf(roleId: string): PermCell {
  return matrix.value[roleId] || EMPTY_CELL
}

function rangeLabel(range: string | null): string {
  switch (range) {
    case 'ALL': return '全部'
    case 'SELF': return '仅本人'
    case 'CURRENT_USER_DEPT': return '本部门'
    default: return range || '—'
  }
}
function rangeVariant(range: string | null): 'success' | 'warn' | 'neutral' {
  if (range === 'ALL') return 'success'
  if (range === 'SELF' || range === 'CURRENT_USER_DEPT') return 'warn'
  return 'neutral'
}

async function load() {
  if (!props.appId || !props.formId) return
  loading.value = true
  error.value = ''
  try {
    const resp = await request.get<any, any>(`/applications/${props.appId}/forms/${props.formId}/permissions`)
    if (resp?.ok) {
      dataRoles.value = resp.roles || []
      matrix.value = resp.matrix || {}
    } else {
      error.value = resp?.message || resp?.error_code || '加载失败'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    loading.value = false
  }
}

watch(() => [props.appId, props.formId], () => load(), { immediate: true })
</script>

<style scoped>
.fpp {
  font-family: var(--font-sans);
  color: var(--text);
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.fpp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-4);
  padding: var(--s-5) var(--s-8);
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.fpp-title { margin: 0 0 var(--s-1); font-size: 18px; font-weight: var(--fw-semibold, 600); color: var(--text); }
.fpp-stat { margin: 0; font-size: 12.5px; color: var(--text-3); }
.fpp-btn {
  height: 30px; padding: 0 var(--s-3); border-radius: var(--r-2, 6px);
  font-size: 12.5px; font-family: inherit; cursor: pointer;
  border: 1px solid var(--line); background: var(--surface); color: var(--text);
  display: inline-flex; align-items: center; gap: var(--s-1); flex-shrink: 0;
}
.fpp-btn:disabled { opacity: .55; cursor: not-allowed; }
.fpp-btn-ghost:hover:not(:disabled) { border-color: var(--brand); color: var(--brand); }
.fpp-banner {
  margin: var(--s-3) var(--s-8) 0;
  padding: var(--s-2) var(--s-3);
  background: var(--brand-soft);
  color: var(--brand);
  border-radius: var(--r-2, 6px);
  font-size: 12.5px;
  line-height: 1.5;
}
.fpp-body { flex: 1; overflow: auto; padding: var(--s-4) var(--s-8); }
.fpp-table-wrap { overflow: auto; }
.fpp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  overflow: hidden;
}
.fpp-table th {
  text-align: center;
  padding: var(--s-3);
  background: var(--surface-2);
  font-weight: var(--fw-medium, 500);
  color: var(--text-3);
  font-size: 12px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.fpp-table td {
  padding: var(--s-3);
  border-bottom: 1px solid var(--line);
  text-align: center;
}
.fpp-table th.fpp-col-role, .fpp-table td.fpp-col-role { text-align: left; white-space: nowrap; }
.fpp-table tr:last-child td { border-bottom: none; }
.fpp-role-name { font-weight: var(--fw-medium, 500); color: var(--text); margin-right: var(--s-2); }
.fpp-on { color: var(--ok); font-weight: var(--fw-semibold, 600); }
.fpp-off { color: var(--text-4); }
</style>

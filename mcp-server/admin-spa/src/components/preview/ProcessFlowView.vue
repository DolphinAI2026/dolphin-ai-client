<template>
  <div class="process-flow">
    <div v-if="!workflows.length" class="empty-state">
      暂无显式流程/审批流。当前草稿会按表单权限完成基础操作流转，导入能力仍跟随权限规则开启。
    </div>

    <div v-else class="process-list">
      <el-card v-for="(workflow, idx) in workflows" :key="idx" class="process-card">
        <div class="process-head">
          <div>
            <div class="process-title">{{ workflow.name || workflow.processName || `流程 ${idx + 1}` }}</div>
            <div class="process-meta">
              {{ workflowForm(workflow) ? `关联表单：${workflowForm(workflow)}` : '未指定关联表单' }}
              <span v-if="workflow.description"> · {{ workflow.description }}</span>
            </div>
          </div>
          <el-tag size="small">{{ normalizeNodes(workflow).length }} 节点</el-tag>
        </div>

        <div class="process-nodes">
          <div
            v-for="(node, nodeIdx) in normalizeNodes(workflow)"
            :key="nodeIdx"
            class="process-node"
            :class="node.kind"
          >
            <div class="name">{{ node.name }}</div>
            <div v-if="node.role" class="role">{{ node.role }}</div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ spec: any }>()

const workflows = computed<any[]>(() => props.spec?.workflows || props.spec?.flows || props.spec?.processes || [])

function workflowForm(workflow: any): string {
  return workflow.form || workflow.formName || workflow.formCode || workflow.bindForm || ''
}

function normalizeNodes(workflow: any) {
  const raw = workflow.nodes || workflow.steps || workflow.approvers || []
  const nodes = raw.map((node: any, idx: number) => {
    const typeText = String(node.type || node.nodeType || node.name || '')
    return {
      name: node.name || node.nodeName || node.title || node.role || node.roleName || `审批节点 ${idx + 1}`,
      role: node.role || node.roleName || node.assignee || node.approver || '',
      kind: /start|开始/i.test(typeText) ? 'start' : /end|结束/i.test(typeText) ? 'end' : '',
    }
  })
  const hasStart = nodes.some((node: any) => node.kind === 'start')
  const hasEnd = nodes.some((node: any) => node.kind === 'end')
  return [
    ...(hasStart ? [] : [{ name: '提交', role: '发起人', kind: 'start' }]),
    ...nodes,
    ...(hasEnd ? [] : [{ name: '结束', role: '', kind: 'end' }]),
  ]
}
</script>

<style scoped>
.process-flow { padding: 20px 40px; }
.process-list { display: grid; gap: 16px; }
.process-card { border-radius: 6px; }
.process-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 14px; }
.process-title { font-size: 16px; font-weight: 600; }
.process-meta { color: #909399; font-size: 12px; margin-top: 4px; }
.process-nodes { display: flex; flex-wrap: wrap; align-items: stretch; gap: 10px; }
.process-node { min-width: 128px; max-width: 190px; border: 1px solid #dcdfe6; border-radius: 6px; padding: 10px 12px; background: #fafafa; position: relative; }
.process-node:not(:last-child)::after { content: "→"; position: absolute; right: -13px; top: 26px; color: #c0c4cc; font-weight: 600; }
.process-node.start { border-color: #b3e19d; background: #f0f9eb; }
.process-node.end { border-color: #fab6b6; background: #fef0f0; }
.process-node .name { font-weight: 600; font-size: 13px; }
.process-node .role { color: #909399; font-size: 11px; margin-top: 4px; }
.empty-state { padding: 56px 20px; text-align: center; color: #909399; background: #fff; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
@media (max-width: 900px) {
  .process-flow { padding: 16px; }
  .process-node:not(:last-child)::after { display: none; }
}
</style>

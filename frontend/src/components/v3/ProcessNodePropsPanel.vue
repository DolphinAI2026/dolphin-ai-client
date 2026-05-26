<!-- ProcessNodePropsPanel.vue — 流程节点属性编辑面板 (Phase C).

  2026-05-26 design-v4 Phase C: 按 node.type 显不同 props 表单. 配合
  ProcessDesignerPanel 用 — Designer 选中节点后 v-model:node 传入这个组件,
  组件内编辑直接改回 reactive node 对象, Designer watch 之后 sync 到 x6.

  支持的 type 分组:
    - entry/exit: start / end / timer / webhook
    - approval:  assignee_approval / role_approval / manager_approval / parallel_approval / cc
    - logic:     condition / multi_branch / parallel_gateway / merge / wait
    - action:    fill_form / write_data / read_data / ai_judge / ai_generate

  保存到 apaas 平台是 P2 (走 set_apaas_app_process MCP) — 本 session 只做 UI 层.
-->
<template>
  <aside class="pnpp" aria-label="节点属性">
    <header class="pnpp-head">
      <div class="pnpp-head-meta">
        <span class="pnpp-type-tag" :data-cat="nodeCategory">{{ nodeTypeLabel }}</span>
        <h4>节点属性</h4>
      </div>
      <button class="pnpp-icon-btn" title="关闭属性面板" @click="$emit('close')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6 6 18M6 6l12 12"/>
        </svg>
      </button>
    </header>

    <div class="pnpp-body">
      <!-- 通用字段: 所有节点都有 名称 + Key -->
      <label class="pnpp-field">
        <span class="pnpp-field-label">名称</span>
        <input class="pnpp-input" v-model="node.label" @input="emitChange" />
      </label>
      <label class="pnpp-field">
        <span class="pnpp-field-label">Key</span>
        <input class="pnpp-input pnpp-input-mono" v-model="node.key" @input="emitChange" placeholder="n3" />
      </label>

      <!-- 入口/出口: timer / webhook 额外字段 -->
      <template v-if="node.type === 'timer'">
        <label class="pnpp-field">
          <span class="pnpp-field-label">Cron 表达式</span>
          <input
            class="pnpp-input pnpp-input-mono"
            v-model="node.cron"
            @input="emitChange"
            placeholder="0 0 9 * * ?"
          />
        </label>
        <label class="pnpp-field">
          <span class="pnpp-field-label">触发说明</span>
          <input class="pnpp-input" v-model="node.description" @input="emitChange" placeholder="每天 9 点" />
        </label>
      </template>

      <template v-if="node.type === 'webhook'">
        <label class="pnpp-field">
          <span class="pnpp-field-label">Webhook URL</span>
          <input
            class="pnpp-input pnpp-input-readonly pnpp-input-mono"
            :value="webhookUrl"
            readonly
            @click="copyWebhookUrl"
          />
        </label>
        <label class="pnpp-field">
          <span class="pnpp-field-label">Secret Token</span>
          <input
            class="pnpp-input pnpp-input-readonly pnpp-input-mono"
            :value="webhookSecret"
            readonly
          />
        </label>
        <p class="pnpp-hint">部署后会生成真实 URL — 当前是占位.</p>
      </template>

      <!-- 审批节点 -->
      <template v-if="isApprovalNode">
        <label class="pnpp-field">
          <span class="pnpp-field-label">审批人</span>
          <div class="pnpp-chip-list">
            <span
              v-for="(p, i) in (node.approvers || [])"
              :key="`${p}-${i}`"
              class="pnpp-chip"
            >
              {{ p }}
              <button
                class="pnpp-chip-x"
                title="移除"
                @click="removeApprover(i)"
              >×</button>
            </span>
            <button class="pnpp-chip-add" @click="addApprover">+ 添加</button>
          </div>
          <span class="pnpp-hint">P2 接人员选择器, 当前手动填名字</span>
        </label>

        <label class="pnpp-field">
          <span class="pnpp-field-label">审批策略</span>
          <select class="pnpp-input" v-model="node.strategy" @change="emitChange">
            <option value="single">单人审批</option>
            <option value="any">或签 (任一通过)</option>
            <option value="all">会签 (全部通过)</option>
            <option value="majority">多数通过</option>
          </select>
        </label>

        <label class="pnpp-field">
          <span class="pnpp-field-label">SLA (小时)</span>
          <input
            class="pnpp-input"
            type="number"
            v-model.number="node.slaHours"
            @input="emitChange"
            placeholder="24"
            min="0"
          />
        </label>

        <div class="pnpp-switches">
          <label class="pnpp-switch">
            <input type="checkbox" v-model="node.timeoutAutoApprove" @change="emitChange" />
            <span>超时自动通过</span>
          </label>
          <label class="pnpp-switch">
            <input type="checkbox" v-model="node.allowAddApprover" @change="emitChange" />
            <span>允许加签</span>
          </label>
          <label class="pnpp-switch">
            <input type="checkbox" v-model="node.allowReject" @change="emitChange" />
            <span>允许退回</span>
          </label>
        </div>
      </template>

      <!-- 条件分支 -->
      <template v-if="node.type === 'condition'">
        <label class="pnpp-field">
          <span class="pnpp-field-label">条件表达式</span>
          <textarea
            class="pnpp-input pnpp-textarea pnpp-input-mono"
            rows="3"
            v-model="node.expression"
            @input="emitChange"
            placeholder="amount > 5000 && department == '财务'"
          ></textarea>
          <span class="pnpp-hint">支持字段引用 + 比较运算 — 真值走"是"分支, 假值走"否"分支</span>
        </label>
        <div class="pnpp-branch-hint">
          <span class="pnpp-branch-row"><span class="pnpp-branch-tag pnpp-branch-true">是</span> 真值分支</span>
          <span class="pnpp-branch-row"><span class="pnpp-branch-tag pnpp-branch-false">否</span> 假值分支</span>
        </div>
      </template>

      <!-- 多分支 -->
      <template v-if="node.type === 'multi_branch'">
        <label class="pnpp-field">
          <span class="pnpp-field-label">分支列表</span>
          <div class="pnpp-branch-list">
            <div
              v-for="(b, i) in (node.branches || [])"
              :key="i"
              class="pnpp-branch-item"
            >
              <input
                class="pnpp-input pnpp-input-mono pnpp-branch-cond"
                v-model="b.condition"
                @input="emitChange"
                placeholder="amount > 10000"
              />
              <input
                class="pnpp-input pnpp-branch-target"
                v-model="b.targetNodeKey"
                @input="emitChange"
                placeholder="跳转节点 Key"
              />
              <button class="pnpp-row-x" @click="removeBranch(i)" title="移除">×</button>
            </div>
            <button class="pnpp-add-row" @click="addBranch">+ 新增分支</button>
          </div>
        </label>
      </template>

      <!-- 等待 -->
      <template v-if="node.type === 'wait'">
        <label class="pnpp-field">
          <span class="pnpp-field-label">等待时长 (分钟)</span>
          <input
            class="pnpp-input"
            type="number"
            v-model.number="node.waitMinutes"
            @input="emitChange"
            placeholder="60"
            min="0"
          />
        </label>
      </template>

      <!-- 写入数据表 -->
      <template v-if="node.type === 'write_data'">
        <label class="pnpp-field">
          <span class="pnpp-field-label">目标表</span>
          <select class="pnpp-input" v-model="node.targetModelCode" @change="emitChange">
            <option value="">— 选择目标表 —</option>
            <option v-for="m in modelOptions" :key="m.code" :value="m.code">
              {{ m.label }}
            </option>
          </select>
          <span class="pnpp-hint">数据来源 list_apaas_app_models — 待右侧配置助手联动</span>
        </label>

        <label class="pnpp-field">
          <span class="pnpp-field-label">字段映射</span>
          <div class="pnpp-branch-list">
            <div
              v-for="(m, i) in (node.fieldMappings || [])"
              :key="i"
              class="pnpp-branch-item"
            >
              <input
                class="pnpp-input pnpp-input-mono"
                style="flex: 1"
                v-model="m.targetField"
                @input="emitChange"
                placeholder="目标字段"
              />
              <span class="pnpp-arrow">←</span>
              <input
                class="pnpp-input pnpp-input-mono"
                style="flex: 1"
                v-model="m.sourceExpr"
                @input="emitChange"
                placeholder="源表达式"
              />
              <button class="pnpp-row-x" @click="removeFieldMapping(i)" title="移除">×</button>
            </div>
            <button class="pnpp-add-row" @click="addFieldMapping">+ 新增映射</button>
          </div>
        </label>
      </template>

      <!-- 读取数据 -->
      <template v-if="node.type === 'read_data'">
        <label class="pnpp-field">
          <span class="pnpp-field-label">数据源表</span>
          <select class="pnpp-input" v-model="node.sourceModelCode" @change="emitChange">
            <option value="">— 选择数据源 —</option>
            <option v-for="m in modelOptions" :key="m.code" :value="m.code">
              {{ m.label }}
            </option>
          </select>
        </label>
        <label class="pnpp-field">
          <span class="pnpp-field-label">过滤条件</span>
          <textarea
            class="pnpp-input pnpp-textarea pnpp-input-mono"
            rows="2"
            v-model="node.filterExpression"
            @input="emitChange"
            placeholder="status == 'open'"
          ></textarea>
        </label>
        <label class="pnpp-field">
          <span class="pnpp-field-label">输出变量</span>
          <input
            class="pnpp-input pnpp-input-mono"
            v-model="node.outputVar"
            @input="emitChange"
            placeholder="result"
          />
        </label>
      </template>

      <!-- 填写表单 -->
      <template v-if="node.type === 'fill_form'">
        <label class="pnpp-field">
          <span class="pnpp-field-label">关联表单</span>
          <input class="pnpp-input pnpp-input-mono" v-model="node.formCode" @input="emitChange" placeholder="form_code" />
        </label>
        <label class="pnpp-field">
          <span class="pnpp-field-label">填写人</span>
          <input class="pnpp-input" v-model="node.assignee" @input="emitChange" placeholder="留空 = 发起人" />
        </label>
      </template>

      <!-- AI 判定 / AI 生成 -->
      <template v-if="node.type === 'ai_judge' || node.type === 'ai_generate'">
        <label class="pnpp-field">
          <span class="pnpp-field-label">Prompt</span>
          <textarea
            class="pnpp-input pnpp-textarea"
            rows="4"
            v-model="node.prompt"
            @input="emitChange"
            :placeholder="node.type === 'ai_judge' ? '判断该申请是否合规, 返回 true / false' : '基于上下文生成审批意见'"
          ></textarea>
        </label>
        <label class="pnpp-field">
          <span class="pnpp-field-label">输出变量</span>
          <input
            class="pnpp-input pnpp-input-mono"
            v-model="node.outputVar"
            @input="emitChange"
            placeholder="ai_result"
          />
        </label>
        <label class="pnpp-field">
          <span class="pnpp-field-label">Model</span>
          <select class="pnpp-input" v-model="node.model" @change="emitChange">
            <option value="gpt-5.5">gpt-5.5 (默认)</option>
            <option value="claude-opus-4-7">claude-opus-4-7</option>
            <option value="claude-sonnet-4-7">claude-sonnet-4-7</option>
            <option value="qwen-plus">qwen-plus</option>
          </select>
        </label>
      </template>

      <!-- 抄送 (cc) 简化为 单 approvers list — 复用 approver 块 -->

      <!-- 底部 AI 提问 -->
      <div class="pnpp-ai-prompt">
        <label class="pnpp-field">
          <span class="pnpp-field-label">问 AI</span>
          <div class="pnpp-ai-row">
            <input
              class="pnpp-input"
              v-model="aiQuery"
              @keyup.enter="onAskAi"
              placeholder="例: 给这个节点加个抄送 HR"
            />
            <button class="pnpp-ai-go" :disabled="!aiQuery.trim()" @click="onAskAi">问</button>
          </div>
          <span class="pnpp-hint">P2 接 ConfigAssistant — 当前是占位</span>
        </label>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ProcessNode, NodeCategoryCode } from './processNodeRegistry'
import { getNodeDef, getNodeCategoryCode } from './processNodeRegistry'

const props = defineProps<{
  node: ProcessNode
  modelOptions?: Array<{ code: string; label: string }>
}>()

const emit = defineEmits<{
  (e: 'change'): void
  (e: 'close'): void
  (e: 'ai-query', query: string): void
}>()

const aiQuery = ref('')

const nodeTypeLabel = computed(() => {
  const def = getNodeDef(props.node.type)
  return def?.label || props.node.type
})

const nodeCategory = computed<NodeCategoryCode | 'unknown'>(() => {
  return getNodeCategoryCode(props.node.type) || 'unknown'
})

const isApprovalNode = computed(() => {
  return ['assignee_approval', 'role_approval', 'manager_approval', 'parallel_approval', 'cc'].includes(props.node.type)
})

const webhookUrl = computed(() => `https://agent.dfy.../webhooks/${props.node.id}`)
const webhookSecret = computed(() => '••••••••••••••••')

function emitChange() {
  emit('change')
}

function addApprover() {
  if (!props.node.approvers) props.node.approvers = []
  const name = prompt('审批人姓名 (P2 接人员选择器)') || ''
  if (name.trim()) {
    props.node.approvers.push(name.trim())
    emitChange()
  }
}

function removeApprover(i: number) {
  if (!props.node.approvers) return
  props.node.approvers.splice(i, 1)
  emitChange()
}

function addBranch() {
  if (!props.node.branches) props.node.branches = []
  props.node.branches.push({ condition: '', targetNodeKey: '' })
  emitChange()
}

function removeBranch(i: number) {
  if (!props.node.branches) return
  props.node.branches.splice(i, 1)
  emitChange()
}

function addFieldMapping() {
  if (!props.node.fieldMappings) props.node.fieldMappings = []
  props.node.fieldMappings.push({ targetField: '', sourceExpr: '' })
  emitChange()
}

function removeFieldMapping(i: number) {
  if (!props.node.fieldMappings) return
  props.node.fieldMappings.splice(i, 1)
  emitChange()
}

function copyWebhookUrl() {
  try { navigator.clipboard?.writeText(webhookUrl.value) } catch { /* ignore */ }
}

function onAskAi() {
  const q = aiQuery.value.trim()
  if (!q) return
  emit('ai-query', q)
  aiQuery.value = ''
}
</script>

<style scoped>
.pnpp {
  width: 320px;
  flex-shrink: 0;
  background: var(--surface);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  font-family: var(--font-sans);
}

.pnpp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
.pnpp-head-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pnpp-head h4 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
}
.pnpp-type-tag {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
  background: var(--brand-soft);
  color: var(--brand);
}
.pnpp-type-tag[data-cat="entry"]    { background: var(--ok-soft);   color: var(--ok); }
.pnpp-type-tag[data-cat="approval"] { background: var(--brand-soft); color: var(--brand); }
.pnpp-type-tag[data-cat="logic"]    { background: var(--warn-soft); color: var(--warn); }
.pnpp-type-tag[data-cat="action"]   { background: var(--info-soft); color: var(--info); }

.pnpp-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.pnpp-icon-btn:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}

.pnpp-body {
  flex: 1;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
}

.pnpp-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pnpp-field-label {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.pnpp-input {
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s;
  box-sizing: border-box;
  width: 100%;
}
.pnpp-input:focus { border-color: var(--brand); }
.pnpp-input:disabled { opacity: 0.5; cursor: not-allowed; }

.pnpp-input-mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
}

.pnpp-input-readonly {
  background: var(--surface-2);
  color: var(--text-3);
  cursor: default;
}

.pnpp-textarea {
  height: auto;
  padding: 8px 10px;
  resize: vertical;
  line-height: 1.5;
}

.pnpp-hint {
  font-size: 11.5px;
  color: var(--text-4);
  line-height: 1.5;
}

/* Approver chip list */
.pnpp-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 5px;
  min-height: 36px;
  background: var(--surface);
}
.pnpp-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 6px 0 10px;
  background: var(--brand-soft);
  color: var(--brand);
  border-radius: 4px;
  font-size: 12.5px;
  font-weight: 500;
}
.pnpp-chip-x {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 13px;
  padding: 0;
  border-radius: 2px;
}
.pnpp-chip-x:hover {
  background: rgba(0, 0, 0, 0.08);
}
.pnpp-chip-add {
  height: 26px;
  padding: 0 10px;
  border: 1px dashed var(--line-strong);
  background: transparent;
  border-radius: 4px;
  font-size: 12px;
  color: var(--text-3);
  cursor: pointer;
  font-family: inherit;
}
.pnpp-chip-add:hover {
  border-color: var(--brand);
  color: var(--brand);
}

/* Switches */
.pnpp-switches {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 4px;
}
.pnpp-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
}
.pnpp-switch input {
  width: 14px;
  height: 14px;
  accent-color: var(--brand);
}

/* Condition branch hints */
.pnpp-branch-hint {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  background: var(--surface-2);
  border-radius: 5px;
}
.pnpp-branch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-2);
}
.pnpp-branch-tag {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
}
.pnpp-branch-true { background: var(--ok-soft); color: var(--ok); }
.pnpp-branch-false { background: var(--err-soft); color: var(--err); }

/* Branch list */
.pnpp-branch-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pnpp-branch-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pnpp-branch-cond { flex: 1; }
.pnpp-branch-target { flex: 1; }
.pnpp-row-x {
  width: 24px;
  height: 30px;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 4px;
  font-size: 14px;
  color: var(--text-3);
  cursor: pointer;
  flex-shrink: 0;
}
.pnpp-row-x:hover {
  border-color: var(--err);
  color: var(--err);
}
.pnpp-add-row {
  height: 30px;
  padding: 0 12px;
  border: 1px dashed var(--line-strong);
  background: transparent;
  border-radius: 5px;
  font-size: 12.5px;
  color: var(--text-3);
  cursor: pointer;
  font-family: inherit;
}
.pnpp-add-row:hover {
  border-color: var(--brand);
  color: var(--brand);
}
.pnpp-arrow {
  color: var(--text-4);
  font-size: 13px;
  flex-shrink: 0;
}

/* AI prompt block */
.pnpp-ai-prompt {
  margin-top: 8px;
  padding-top: 14px;
  border-top: 1px dashed var(--line);
}
.pnpp-ai-row {
  display: flex;
  gap: 6px;
}
.pnpp-ai-row .pnpp-input { flex: 1; }
.pnpp-ai-go {
  height: 32px;
  padding: 0 14px;
  background: var(--brand);
  color: #fff;
  border: none;
  border-radius: 5px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
}
.pnpp-ai-go:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.pnpp-ai-go:hover:not(:disabled) {
  background: var(--brand-hover);
}
</style>

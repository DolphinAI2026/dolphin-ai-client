<template>
  <div class="design-doc-card">
    <div class="ddc-header">
      <span class="ddc-title">功能设计文档</span>
      <span class="ddc-badge">{{ docResult.tables?.length || 0 }} 表 / {{ docResult.roles?.length || 0 }} 角色 / {{ docResult.data_dictionary?.length || 0 }} 字典</span>
    </div>

    <!-- 应用信息 -->
    <div class="ddc-section" v-if="docResult.app_info">
      <div class="ddc-section-head">
        <span class="ddc-icon"><AppIcon name="smartphone" :size="14" /></span>
        <span>{{ docResult.app_info.name }}</span>
        <code class="ddc-code">{{ docResult.app_info.code }}</code>
      </div>
      <p class="ddc-desc">{{ docResult.app_info.description }}</p>
    </div>

    <!-- 角色 -->
    <div class="ddc-section" v-if="docResult.roles?.length">
      <div class="ddc-section-head" @click="toggleSection('roles')">
        <span class="ddc-icon"><AppIcon name="users" :size="14" /></span>
        <span>角色清单</span>
        <span class="ddc-count">{{ docResult.roles.length }}</span>
        <span class="ddc-arrow" :class="{ open: openSections.has('roles') }">▸</span>
      </div>
      <div v-if="openSections.has('roles')" class="ddc-body">
        <div v-for="r in docResult.roles" :key="r.role_code" class="ddc-item">
          <code>{{ r.role_code }}</code>
          <strong>{{ r.role_name }}</strong>
          <span class="ddc-muted">{{ r.description }}</span>
        </div>
      </div>
    </div>

    <!-- 数据字典 -->
    <div class="ddc-section" v-if="docResult.data_dictionary?.length">
      <div class="ddc-section-head" @click="toggleSection('dicts')">
        <span class="ddc-icon"><AppIcon name="book" :size="14" /></span>
        <span>数据字典</span>
        <span class="ddc-count">{{ docResult.data_dictionary.length }}</span>
        <span class="ddc-arrow" :class="{ open: openSections.has('dicts') }">▸</span>
      </div>
      <div v-if="openSections.has('dicts')" class="ddc-body">
        <div v-for="d in docResult.data_dictionary" :key="d.dict_code" class="ddc-dict">
          <div class="ddc-dict-name">{{ d.dict_name }} <code>{{ d.dict_code }}</code></div>
          <div class="ddc-tags">
            <span v-for="item in d.items" :key="item.item_code" class="ddc-tag">{{ item.item_name }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 数据表 -->
    <div class="ddc-section" v-if="docResult.tables?.length">
      <div class="ddc-section-head" @click="toggleSection('tables')">
        <span class="ddc-icon"><AppIcon name="database" :size="14" /></span>
        <span>数据表</span>
        <span class="ddc-count">{{ docResult.tables.length }}</span>
        <span class="ddc-arrow" :class="{ open: openSections.has('tables') }">▸</span>
      </div>
      <div v-if="openSections.has('tables')" class="ddc-body">
        <div v-for="t in docResult.tables" :key="t.table_code" class="ddc-table">
          <div class="ddc-table-head">
            <strong>{{ t.table_name }}</strong>
            <code>{{ t.table_code }}</code>
            <span class="ddc-table-type" :class="t.table_type === '子表' ? 'sub' : ''">{{ t.table_type }}</span>
          </div>
          <div class="ddc-fields">
            <span v-for="f in t.fields?.slice(0, 8)" :key="f.field_code" class="ddc-field">{{ f.field_name }}</span>
            <span v-if="(t.fields?.length || 0) > 8" class="ddc-field more">+{{ t.fields.length - 8 }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 权限 -->
    <div class="ddc-section" v-if="docResult.role_table_mapping?.length">
      <div class="ddc-section-head" @click="toggleSection('perms')">
        <span class="ddc-icon"><AppIcon name="lock" :size="14" /></span>
        <span>权限矩阵</span>
        <span class="ddc-count">{{ docResult.role_table_mapping.length }}</span>
        <span class="ddc-arrow" :class="{ open: openSections.has('perms') }">▸</span>
      </div>
      <div v-if="openSections.has('perms')" class="ddc-body ddc-perms-brief">
        <div v-for="m in docResult.role_table_mapping" :key="m.table_code" class="ddc-perm-row">
          <strong>{{ m.table_name }}</strong>
          <span v-for="p in m.permissions?.slice(0, 3)" :key="p.role_code" class="ddc-perm-role">
            {{ p.role_name }}: {{ p.operations?.length || 0 }} 项操作
          </span>
        </div>
      </div>
    </div>

    <!-- JSON 编辑区域 -->
    <div v-if="editMode" class="ddc-edit-area">
      <div class="ddc-edit-header">
        <span>编辑设计文档 (JSON)</span>
        <div class="ddc-edit-btns">
          <button class="ddc-btn secondary" @click="cancelEdit">取消</button>
          <button class="ddc-btn primary" @click="saveEdit">保存修改</button>
        </div>
      </div>
      <textarea
        v-model="editJson"
        class="ddc-json-editor"
        spellcheck="false"
        rows="20"
      ></textarea>
      <p v-if="editError" class="ddc-edit-error">{{ editError }}</p>
    </div>

    <!-- 操作按钮 -->
    <div v-if="!editMode && showActions !== false" class="ddc-actions">
      <button class="ddc-btn secondary" @click="startEdit">编辑详情</button>
      <button class="ddc-btn primary" @click="$emit('confirm')" :disabled="confirming">
        {{ confirming ? '正在生成...' : '确认并开始生成 →' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'

const props = defineProps<{
  docResult: any
  confirming?: boolean
  showActions?: boolean
}>()

const emit = defineEmits<{
  edit: [updatedDoc: any]
  confirm: []
}>()

const openSections = ref(new Set<string>())
const editMode = ref(false)
const editJson = ref('')
const editError = ref('')

function toggleSection(key: string) {
  if (openSections.value.has(key)) {
    openSections.value.delete(key)
  } else {
    openSections.value.add(key)
  }
}

function startEdit() {
  editJson.value = JSON.stringify(props.docResult, null, 2)
  editError.value = ''
  editMode.value = true
}

function cancelEdit() {
  editMode.value = false
  editError.value = ''
}

function saveEdit() {
  try {
    const parsed = JSON.parse(editJson.value)
    emit('edit', parsed)
    editMode.value = false
    editError.value = ''
  } catch (e: any) {
    editError.value = 'JSON 格式错误: ' + e.message
  }
}
</script>

<style scoped>
.design-doc-card {
  border: 1px solid var(--t-border-strong);
  border-radius: 12px;
  overflow: hidden;
  background: var(--t-bg-panel);
  margin-top: 8px;
  box-shadow: var(--t-shadow-sm);
}

.ddc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--t-brand-subtle);
  border-bottom: 1px solid var(--t-border-subtle);
}
.ddc-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--t-brand-text);
}
.ddc-badge {
  font-size: 11px;
  color: var(--t-text-muted);
}

.ddc-section {
  border-bottom: 1px solid var(--t-border-subtle);
}
.ddc-section:last-of-type {
  border-bottom: none;
}
.ddc-section-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--t-text-primary);
  cursor: pointer;
  transition: background 0.15s;
}
.ddc-section-head:hover {
  background: var(--t-bg-panel-hover);
}
.ddc-icon {
  font-size: 14px;
}
.ddc-count {
  font-size: 10px;
  background: var(--t-brand);
  color: #fff;
  border-radius: 8px;
  padding: 0 5px;
  line-height: 16px;
}
.ddc-arrow {
  margin-left: auto;
  font-size: 10px;
  color: var(--t-text-muted);
  transition: transform 0.2s;
}
.ddc-arrow.open {
  transform: rotate(90deg);
}
.ddc-code {
  font-size: 11px;
  color: var(--t-brand-text);
  background: var(--t-brand-subtle);
  padding: 1px 5px;
  border-radius: 4px;
  margin-left: 4px;
}
.ddc-desc {
  font-size: 12px;
  color: var(--t-text-secondary);
  margin: 0;
  padding: 0 14px 8px;
}
.ddc-body {
  padding: 4px 14px 10px;
}
.ddc-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  padding: 3px 0;
}
.ddc-item code {
  font-size: 11px;
  color: var(--t-brand-text);
  background: var(--t-brand-subtle);
  padding: 0 4px;
  border-radius: 3px;
  flex-shrink: 0;
}
.ddc-item strong {
  color: var(--t-text-primary);
  flex-shrink: 0;
}
.ddc-muted {
  color: var(--t-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Dicts */
.ddc-dict {
  margin-bottom: 6px;
}
.ddc-dict-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--t-text-primary);
  margin-bottom: 3px;
}
.ddc-dict-name code {
  font-size: 10px;
  color: var(--t-text-muted);
  background: var(--t-bg-input);
  padding: 0 4px;
  border-radius: 3px;
  margin-left: 4px;
}
.ddc-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}
.ddc-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
}

/* Tables */
.ddc-table {
  margin-bottom: 6px;
  padding: 6px 8px;
  background: var(--t-bg-base);
  border-radius: 6px;
}
.ddc-table-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  font-size: 12px;
}
.ddc-table-head strong {
  color: var(--t-text-primary);
}
.ddc-table-head code {
  font-size: 10px;
  color: var(--t-text-muted);
}
.ddc-table-type {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--t-brand-subtle);
  color: var(--t-brand-text);
}
.ddc-table-type.sub {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}
.ddc-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}
.ddc-field {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--t-bg-panel);
  color: var(--t-text-secondary);
  border: 1px solid var(--t-border-subtle);
}
.ddc-field.more {
  color: var(--t-text-muted);
  border: none;
  background: none;
}

/* Permissions brief */
.ddc-perms-brief {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ddc-perm-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  flex-wrap: wrap;
}
.ddc-perm-row strong {
  color: var(--t-text-primary);
  font-size: 12px;
}
.ddc-perm-role {
  color: var(--t-text-muted);
}

/* Actions */
.ddc-actions {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid var(--t-border-subtle);
  justify-content: flex-end;
}
.ddc-btn {
  padding: 6px 16px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  border: none;
}
.ddc-btn.secondary {
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
}
.ddc-btn.secondary:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-primary);
}
.ddc-btn.primary {
  background: var(--t-brand-gradient);
  color: #fff;
}
.ddc-btn.primary:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
}
.ddc-btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Edit mode */
.ddc-edit-area {
  padding: 10px 14px;
  border-top: 1px solid var(--t-border-subtle);
}
.ddc-edit-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--t-text-primary);
}
.ddc-edit-btns {
  display: flex;
  gap: 6px;
}
.ddc-json-editor {
  width: 100%;
  font-family: 'SF Mono', 'Consolas', monospace;
  font-size: 11px;
  line-height: 1.5;
  padding: 10px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  background: var(--t-bg-input);
  color: var(--t-text-primary);
  resize: vertical;
  outline: none;
}
.ddc-json-editor:focus {
  border-color: var(--t-brand);
}
.ddc-edit-error {
  margin: 6px 0 0;
  font-size: 11px;
  color: var(--t-danger, #ef4444);
}
</style>

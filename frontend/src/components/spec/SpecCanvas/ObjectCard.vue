<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { ObjectSpec } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps<{ object: ObjectSpec }>()
const spec = useSpecStore()

async function confirmObject() {
  try {
    await spec.updateItem('object', props.object.code, 'confirm')
    ElMessage.success(`已确认对象：${props.object.name}`)
  } catch (e: unknown) {
    ElMessage.error(`确认失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismissObject() {
  try { await ElMessageBox.confirm(`删除对象「${props.object.name}」及其全部字段？`, '确认删除', { type: 'warning' }) }
  catch { return }
  try {
    await spec.updateItem('object', props.object.code, 'dismiss')
    ElMessage.success(`已删除对象：${props.object.name}`)
  } catch (e: unknown) {
    ElMessage.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function confirmField(fieldCode: string) {
  try {
    await spec.updateItem('field', fieldCode, 'confirm', { object_code: props.object.code })
    ElMessage.success('字段已确认')
  } catch (e: unknown) {
    ElMessage.error(`确认失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismissField(fieldCode: string, fieldName: string) {
  try { await ElMessageBox.confirm(`删除字段「${fieldName}」？`, '确认删除', { type: 'warning' }) }
  catch { return }
  try {
    await spec.updateItem('field', fieldCode, 'dismiss', { object_code: props.object.code })
    ElMessage.success('字段已删除')
  } catch (e: unknown) {
    ElMessage.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <article class="spec-card object-card" :class="{ confirmed: object.confirmed }">
    <header class="spec-card-header">
      <h4 class="spec-card-title">📋 {{ object.name }} <span class="spec-card-code">{{ object.code }}</span></h4>
    </header>
    <p v-if="object.description" class="spec-card-desc">{{ object.description }}</p>
    <ul class="field-list">
      <li v-for="f in object.fields" :key="f.code" class="field-item" :class="{ confirmed: f.confirmed }">
        <span class="field-name">{{ f.name }}</span>
        <span class="field-type">{{ f.type }}</span>
        <span class="field-code">{{ f.code }}</span>
        <span v-if="f.required" class="field-req">必填</span>
        <span class="field-actions">
          <template v-if="!f.confirmed">
            <button class="action-btn confirm" @click="confirmField(f.code)">✓</button>
            <button class="action-btn dismiss" @click="dismissField(f.code, f.name)">✕</button>
          </template>
          <span v-else class="field-status">✓</span>
        </span>
      </li>
    </ul>
    <footer class="spec-card-actions">
      <span v-if="object.confirmed" class="spec-card-status">✓ 已确认</span>
      <template v-else>
        <button class="action-btn confirm" @click="confirmObject">✓ 确认整个对象</button>
        <button class="action-btn dismiss" @click="dismissObject">✕ 删除对象</button>
      </template>
    </footer>
  </article>
</template>

<style scoped>
.object-card { padding: 14px 16px; }
.field-list { list-style: none; padding: 0; margin: 8px 0; border-top: 1px dashed var(--t-border-subtle); }
.field-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px dashed var(--t-border-subtle); font-size: 13px; }
.field-item.confirmed { color: var(--t-success); }
.field-name { font-weight: 500; min-width: 100px; }
.field-type { color: var(--t-text-secondary); font-size: 12px; }
.field-code { font-family: monospace; font-size: 11px; color: var(--t-text-muted); }
.field-req { background: var(--t-warning-subtle); color: var(--t-warning); padding: 1px 6px; border-radius: 3px; font-size: 11px; }
.field-actions { margin-left: auto; display: flex; gap: 4px; }
.field-actions .action-btn { padding: 2px 6px; font-size: 11px; }
.field-status { color: var(--t-success); font-weight: 600; }
.spec-card { border: 1px solid var(--t-border-subtle); border-radius: var(--t-radius-md); padding: 12px 14px; background: var(--t-bg-panel); }
.spec-card.confirmed { border-color: var(--t-success); background: var(--t-success-subtle); }
.spec-card-header { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.spec-card-title { margin: 0; font-size: 14px; color: var(--t-text-primary); }
.spec-card-code { font-family: monospace; font-size: 12px; color: var(--t-text-muted); }
.spec-card-desc { margin: 6px 0; font-size: 13px; color: var(--t-text-secondary); }
.spec-card-actions { display: flex; gap: 8px; margin-top: 8px; }
.action-btn { padding: 4px 10px; font-size: 12px; border: 1px solid var(--t-border-subtle); border-radius: var(--t-radius-sm); background: var(--t-bg-input); cursor: pointer; }
.action-btn.confirm:hover { background: var(--t-success-subtle); border-color: var(--t-success); color: var(--t-success); }
.action-btn.dismiss:hover { background: var(--t-danger-subtle); border-color: var(--t-danger); color: var(--t-danger); }
.spec-card-status { color: var(--t-success); font-size: 12px; font-weight: 600; }
</style>

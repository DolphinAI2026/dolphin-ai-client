<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { ObjectSpec } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps<{ object: ObjectSpec }>()
const spec = useSpecStore()

async function confirmObject() {
  try {
    await spec.updateItem('object', props.object.code, 'confirm')
    ElMessage.success(`已采纳对象：${props.object.name}`)
  } catch (e: unknown) {
    ElMessage.error(`采纳失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismissObject() {
  try { await ElMessageBox.confirm(`忽略对象「${props.object.name}」及其全部字段？忽略后将不进入本轮生成草稿。`, '忽略对象', { type: 'warning' }) }
  catch { return }
  try {
    await spec.updateItem('object', props.object.code, 'dismiss')
    ElMessage.success(`已忽略对象：${props.object.name}`)
  } catch (e: unknown) {
    ElMessage.error(`忽略失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function confirmField(fieldCode: string) {
  try {
    await spec.updateItem('field', fieldCode, 'confirm', { object_code: props.object.code })
    ElMessage.success('字段已采纳')
  } catch (e: unknown) {
    ElMessage.error(`采纳失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismissField(fieldCode: string, fieldName: string) {
  try { await ElMessageBox.confirm(`忽略字段「${fieldName}」？忽略后将不进入本轮生成草稿。`, '忽略字段', { type: 'warning' }) }
  catch { return }
  try {
    await spec.updateItem('field', fieldCode, 'dismiss', { object_code: props.object.code })
    ElMessage.success('字段已忽略')
  } catch (e: unknown) {
    ElMessage.error(`忽略失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <article class="spec-card object-card" :class="{ confirmed: object.confirmed }">
    <header class="spec-card-header">
      <h4 class="spec-card-title">{{ object.name }} <span class="spec-card-code">{{ object.code }}</span></h4>
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
            <button class="action-btn confirm" title="采纳字段" aria-label="采纳字段" @click="confirmField(f.code)">✓</button>
            <button class="action-btn dismiss" title="忽略字段" aria-label="忽略字段" @click="dismissField(f.code, f.name)">忽</button>
          </template>
          <span v-else class="field-status">✓</span>
        </span>
      </li>
    </ul>
    <footer class="spec-card-actions">
      <span v-if="object.confirmed" class="spec-card-status">✓ 已采纳</span>
      <template v-else>
        <button class="action-btn confirm" @click="confirmObject">✓ 采纳对象</button>
        <button class="action-btn dismiss" @click="dismissObject">忽略对象</button>
      </template>
    </footer>
  </article>
</template>

<style scoped>
.object-card { padding: 14px 16px; }
.field-list {
  list-style: none;
  padding: 0;
  margin: 10px 0 0;
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
  overflow: hidden;
}
.field-item {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(72px, 96px) minmax(100px, 0.8fr) auto auto;
  align-items: center;
  gap: 10px;
  min-height: 34px;
  padding: 7px 10px;
  border-bottom: 1px solid var(--t-border-subtle);
  font-size: 13px;
}
.field-item:last-child { border-bottom: 0; }
.field-item.confirmed {
  background: var(--t-bg-subtle);
}
.field-name { font-weight: 600; min-width: 0; color: var(--t-text-primary); }
.field-type { color: var(--t-text-secondary); font-size: 12px; }
.field-code { font-family: monospace; font-size: 11px; color: var(--t-text-muted); min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.field-req { background: var(--t-warning-subtle); color: var(--t-warning); padding: 1px 6px; border-radius: 999px; font-size: 11px; }
.field-actions { margin-left: auto; display: flex; gap: 4px; }
.field-actions .action-btn { width: 24px; height: 24px; padding: 0; font-size: 11px; }
.field-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: var(--t-success-subtle);
  color: var(--t-success);
  font-weight: 700;
}
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

@media (max-width: 760px) {
  .field-item {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .field-type,
  .field-code,
  .field-req {
    grid-column: 1 / -1;
  }
}
</style>

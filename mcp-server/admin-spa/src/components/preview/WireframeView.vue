<template>
  <div class="wireframe-view">
    <div class="layout">
      <!-- 左侧表单列表 -->
      <div class="form-list">
        <div
          v-for="(form, idx) in forms"
          :key="idx"
          class="form-item"
          :class="{ active: idx === activeIdx }"
          @click="activeIdx = idx"
        >
          <div class="name">{{ form.name || form.formName }}</div>
          <div class="meta">{{ countMainFields(form) }} 字段 · {{ countSubForms(form) }} 子表</div>
        </div>
        <div v-if="!forms.length" class="empty">暂无表单</div>
      </div>

      <!-- 右侧画布 -->
      <div class="canvas">
        <FormWireframe v-if="activeForm" :form="activeForm" :spec="spec" />
        <div v-else class="empty-canvas">从左侧选择一个表单</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import FormWireframe from './FormWireframe.vue'

const props = defineProps<{ spec: any }>()
const forms = computed(() => props.spec?.forms || [])
const activeIdx = ref(0)
const activeForm = computed(() => forms.value[activeIdx.value])

function countMainFields(form: any): number {
  return (form.fields || form.components || []).filter((field: any) => (field.sectionType || 'main') !== 'sub').length
}

function countSubForms(form: any): number {
  const labels = new Set<string>()
  for (const field of (form.fields || form.components || [])) {
    if (field.sectionType === 'sub') labels.add(field.subTableLabel || field.subFormName || '子表')
  }
  for (const sub of (form.subForms || [])) labels.add(sub.name || sub.subFormName || '子表')
  return labels.size
}
</script>

<style scoped>
.wireframe-view { padding: 20px 40px; }
.layout { display: grid; grid-template-columns: 220px 1fr; gap: 16px; }
.form-list {
  background: #fff;
  border-radius: 6px;
  padding: 8px 0;
  box-shadow: 0 1px 2px rgba(0,0,0,.04);
  min-height: 600px;
}
.form-item {
  padding: 12px 16px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all .15s;
}
.form-item:hover { background: #f5f7fa; }
.form-item.active {
  background: #ecf5ff;
  border-left-color: #409eff;
}
.form-item.active .name { color: #409eff; }
.form-item .name { font-size: 14px; font-weight: 500; }
.form-item .meta { font-size: 11px; color: #909399; margin-top: 4px; }
.canvas {
  background: #fff;
  border-radius: 6px;
  padding: 24px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04);
  min-height: 600px;
}
.empty, .empty-canvas {
  text-align: center;
  color: #c0c4cc;
  padding: 40px 0;
}
</style>

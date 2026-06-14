<template>
  <el-dialog v-model="previewModel" :title="previewTitle" width="860px" class="doc-preview-dialog" destroy-on-close>
    <div v-if="previewStructuredResult" class="doc-preview-body structured-doc-host">
      <StructuredDocRenderer :doc-result="previewStructuredResult" />
    </div>
    <pre v-else class="doc-preview-body plain-doc-fallback">{{ previewContent }}</pre>
  </el-dialog>

  <el-dialog
    v-model="fullscreenModel"
    :title="fullscreenTitle"
    width="96vw"
    top="2vh"
    class="doc-preview-dialog doc-preview-dialog-fullscreen"
    destroy-on-close
  >
    <div v-if="fullscreenStructuredResult" class="doc-preview-body fullscreen structured-doc-host">
      <StructuredDocRenderer :doc-result="fullscreenStructuredResult" />
    </div>
    <pre v-else class="doc-preview-body fullscreen plain-doc-fallback">{{ fullscreenContent }}</pre>
  </el-dialog>

  <el-dialog v-model="diffModel" title="文档版本对比" width="1220px" class="doc-diff-dialog" destroy-on-close>
    <div class="diff-summary-bar">
      <span class="diff-stat added">新增 {{ diffStats.added }}</span>
      <span class="diff-stat removed">删除 {{ diffStats.removed }}</span>
      <span class="diff-stat modified">修改 {{ diffStats.modified }}</span>
      <span class="diff-stat unchanged">未变更 {{ diffStats.same }}</span>
    </div>
    <div class="doc-diff-container">
      <div class="diff-changes-panel">
        <div class="dcp-title">变更摘要</div>
        <div class="dcp-list">
          <div v-if="diffChangeSummary.length === 0" class="dcp-empty">暂无结构化摘要</div>
          <div v-for="(item, idx) in diffChangeSummary" :key="`${item.type}-${idx}`" class="dcp-item" :class="item.type">
            <span class="dcp-icon">{{ item.type === 'added' ? '+' : item.type === 'removed' ? '-' : '~' }}</span>
            <span class="dcp-text">{{ item.text }}</span>
          </div>
        </div>
      </div>
      <div class="doc-diff-pane">
        <div class="doc-diff-pane-title">{{ diffLeftTitle }}</div>
        <div class="doc-diff-content">
          <div v-if="diffLeftStructuredResult" class="doc-diff-structured structured-doc-host">
            <StructuredDocDiffRenderer :doc-result="diffLeftStructuredResult" :diff-meta="structuredDocDiffMeta.left" />
          </div>
          <template v-else>
            <div
              v-for="(line, idx) in docDiffResult.left"
              :key="`left-${idx}`"
              class="doc-diff-line"
              :class="line.type"
            >
              <span class="doc-diff-lineno">{{ idx + 1 }}</span>
              <span class="doc-diff-text">{{ line.text || ' ' }}</span>
            </div>
          </template>
        </div>
      </div>
      <div class="doc-diff-pane">
        <div class="doc-diff-pane-title">{{ diffRightTitle }}</div>
        <div class="doc-diff-content">
          <div v-if="diffRightStructuredResult" class="doc-diff-structured structured-doc-host">
            <StructuredDocDiffRenderer :doc-result="diffRightStructuredResult" :diff-meta="structuredDocDiffMeta.right" />
          </div>
          <template v-else>
            <div
              v-for="(line, idx) in docDiffResult.right"
              :key="`right-${idx}`"
              class="doc-diff-line"
              :class="line.type"
            >
              <span class="doc-diff-lineno">{{ idx + 1 }}</span>
              <span class="doc-diff-text">{{ line.text || ' ' }}</span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StructuredDocRenderer from '@/components/StructuredDocRenderer.vue'
import StructuredDocDiffRenderer from '@/components/StructuredDocDiffRenderer.vue'

const props = withDefaults(defineProps<{
  previewVisible: boolean
  previewTitle: string
  previewStructuredResult: any | null
  previewContent: string
  fullscreenVisible: boolean
  fullscreenTitle: string
  fullscreenStructuredResult: any | null
  fullscreenContent: string
  diffVisible: boolean
  diffStats: { added: number; removed: number; modified: number; same: number }
  diffChangeSummary: Array<{ type: string; text: string }>
  diffLeftTitle: string
  diffRightTitle: string
  diffLeftStructuredResult: any | null
  diffRightStructuredResult: any | null
  structuredDocDiffMeta: { left: any; right: any }
  docDiffResult: { left: Array<{ type: string; text: string }>; right: Array<{ type: string; text: string }> }
}>(), {
  previewTitle: '',
  previewContent: '',
  fullscreenTitle: '',
  fullscreenContent: '',
})

const emit = defineEmits<{
  (e: 'update:previewVisible', value: boolean): void
  (e: 'update:fullscreenVisible', value: boolean): void
  (e: 'update:diffVisible', value: boolean): void
}>()

const previewModel = computed({
  get: () => props.previewVisible,
  set: value => emit('update:previewVisible', value),
})
const fullscreenModel = computed({
  get: () => props.fullscreenVisible,
  set: value => emit('update:fullscreenVisible', value),
})
const diffModel = computed({
  get: () => props.diffVisible,
  set: value => emit('update:diffVisible', value),
})
</script>

<style scoped>
:global(.doc-preview-dialog) .el-dialog {
  background: var(--t-bg-panel);
  color: var(--t-text-primary);
}
:global(.doc-preview-dialog) .el-dialog__header {
  border-bottom: 1px solid var(--t-border-subtle);
}
:global(.doc-preview-dialog) .el-dialog__title {
  color: var(--t-text-primary);
}
:global(.doc-preview-dialog) .el-dialog__headerbtn .el-dialog__close {
  color: var(--t-text-secondary);
}
:global(.doc-preview-dialog-fullscreen) .el-dialog {
  height: 96vh;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
}
:global(.doc-preview-dialog-fullscreen) .el-dialog__body {
  flex: 1;
  min-height: 0;
  padding: 16px 20px 20px;
}
.doc-preview-body {
  max-height: 70vh;
  overflow-y: auto;
  overflow-x: auto;
  padding: 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--t-text-primary);
  background: var(--t-bg-base);
  border-radius: 8px;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.doc-preview-body.fullscreen {
  max-height: none;
  height: 100%;
  min-height: 0;
}
.doc-preview-body :deep(h1) { font-size: 20px; color: var(--t-text-primary); margin: 20px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--t-border-subtle); }
.doc-preview-body :deep(h2) { font-size: 17px; color: var(--t-text-primary); margin: 18px 0 10px; }
.doc-preview-body :deep(h3) { font-size: 15px; color: var(--t-text-primary); margin: 14px 0 8px; }
.doc-preview-body :deep(h4) { font-size: 13px; color: var(--t-text-primary); margin: 10px 0 6px; }
.doc-preview-body :deep(p) { margin: 6px 0; }
.doc-preview-body :deep(ul),
.doc-preview-body :deep(ol) { padding-left: 20px; margin: 6px 0; }
.doc-preview-body :deep(li) { margin: 3px 0; }
.doc-preview-body :deep(code) { background: var(--t-border-subtle); padding: 2px 6px; border-radius: 4px; font-size: 12px; }
.doc-preview-body :deep(pre) { background: var(--t-border-subtle); padding: 12px; border-radius: 8px; overflow-x: auto; }
.doc-preview-body :deep(.doc-table-scroll) { width: 100%; overflow-x: auto; margin: 10px 0; }
.doc-preview-body :deep(table) {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  margin: 0;
  font-size: 12px;
  table-layout: auto;
}
.doc-preview-body :deep(table td),
.doc-preview-body :deep(table th) {
  white-space: normal;
  overflow-wrap: break-word;
}
.doc-preview-body :deep(th) {
  background: var(--t-brand-subtle);
  color: var(--t-brand-light);
  text-align: left;
  padding: 8px 12px;
  border: 1px solid var(--t-border-subtle);
  font-weight: 600;
  white-space: nowrap;
  word-break: keep-all;
}
.doc-preview-body :deep(td) {
  padding: 6px 12px;
  border: 1px solid var(--t-border-subtle);
  white-space: nowrap;
  word-break: keep-all;
  overflow-wrap: normal;
}
.doc-preview-body :deep(tr:hover td) { background: var(--t-bg-subtle); }
.doc-preview-body :deep(strong) { color: var(--t-text-primary); font-weight: 600; }
.doc-preview-body :deep(hr) { border: none; border-top: 1px solid var(--t-border-subtle); margin: 16px 0; }
:global(.doc-diff-dialog) .el-dialog {
  background: var(--t-bg-panel);
  color: var(--t-text-primary);
}
:global(.doc-diff-dialog) .el-dialog__header {
  border-bottom: 1px solid var(--t-border-subtle);
}
:global(.doc-diff-dialog) .el-dialog__title {
  color: var(--t-text-primary);
}
:global(.doc-diff-dialog) .el-dialog__headerbtn .el-dialog__close {
  color: var(--t-text-secondary);
}
.diff-summary-bar {
  display: flex;
  gap: 16px;
  padding: 10px 14px;
  margin-bottom: 12px;
  background: var(--t-border-subtle);
  border-radius: 10px;
  border: 1px solid var(--t-border-subtle);
}
.diff-stat { font-size: 13px; font-weight: 500; }
.diff-stat.added { color: var(--t-success); }
.diff-stat.removed { color: var(--t-danger); }
.diff-stat.modified { color: var(--t-warning); }
.diff-stat.unchanged { color: var(--t-text-muted); }
.doc-diff-container { display: flex; gap: 8px; max-height: 70vh; }
.diff-changes-panel {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--t-border-subtle);
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
  overflow: hidden;
}
.dcp-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-secondary);
  padding: 10px 12px;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-subtle);
}
.dcp-list { flex: 1; overflow-y: auto; padding: 8px; }
.dcp-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 5px 6px;
  font-size: 11px;
  line-height: 1.4;
  border-radius: 6px;
  margin-bottom: 2px;
}
.dcp-item.added { color: var(--t-success); background: rgba(52, 211, 153, 0.06); }
.dcp-item.removed { color: var(--t-danger); background: rgba(248, 113, 113, 0.06); }
.dcp-item.modified { color: var(--t-warning); background: rgba(251, 191, 36, 0.06); }
.dcp-icon { font-weight: 700; flex-shrink: 0; width: 14px; text-align: center; }
.dcp-text { word-break: break-all; }
.dcp-empty { text-align: center; color: var(--t-text-muted); font-size: 11px; padding: 20px 0; }
.doc-diff-pane { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.doc-diff-pane-title {
  font-size: 12px;
  font-weight: 600;
  padding: 8px 12px;
  background: var(--t-border-subtle);
  border-radius: 8px 8px 0 0;
  color: var(--t-text-secondary);
  border: 1px solid var(--t-border-subtle);
  border-bottom: none;
}
.doc-diff-content {
  flex: 1;
  overflow-y: auto;
  background: var(--t-bg-base);
  border-radius: 0 0 8px 8px;
  border: 1px solid var(--t-border-subtle);
  font-size: 12px;
  font-family: Menlo, Monaco, monospace;
}
.doc-diff-structured {
  padding: 14px 16px 18px;
  font-family: inherit;
}
.doc-diff-structured :deep(.structured-doc) { font-size: 13px; }
.doc-diff-structured :deep(.doc-app-name) { font-size: 28px; margin-bottom: 10px; }
.doc-diff-structured :deep(.doc-section) { margin-bottom: 18px; }
.doc-diff-structured :deep(.doc-section-title) { font-size: 18px; margin-bottom: 10px; }
.doc-diff-structured :deep(.doc-subsection-title) { font-size: 15px; }
.doc-diff-structured :deep(.doc-table) { font-size: 12px; }
.doc-diff-structured :deep(th),
.doc-diff-structured :deep(td) { padding: 6px 10px; }
.doc-diff-line { display: flex; min-height: 20px; line-height: 20px; }
.doc-diff-lineno {
  width: 36px;
  text-align: right;
  padding-right: 8px;
  flex-shrink: 0;
  color: var(--t-text-muted);
  user-select: none;
}
.doc-diff-text { flex: 1; padding: 0 8px; white-space: pre-wrap; word-break: break-all; color: var(--t-text-secondary); }
.doc-diff-line.removed { background: rgba(239, 68, 68, 0.12); }
.doc-diff-line.removed .doc-diff-text { color: #fca5a5; }
.doc-diff-line.added { background: rgba(34, 197, 94, 0.12); }
.doc-diff-line.added .doc-diff-text { color: #86efac; }
</style>

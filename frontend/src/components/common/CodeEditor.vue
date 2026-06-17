<script setup lang="ts">
import { ref, shallowRef, onMounted, onBeforeUnmount, watch } from 'vue'
import { EditorState, type Extension } from '@codemirror/state'
import { EditorView, keymap, lineNumbers, highlightActiveLine } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { markdown } from '@codemirror/lang-markdown'
import { python } from '@codemirror/lang-python'
import { json } from '@codemirror/lang-json'
import { yaml } from '@codemirror/lang-yaml'
import { javascript } from '@codemirror/lang-javascript'

const props = defineProps<{ modelValue: string; filename?: string; readonly?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const host = ref<HTMLDivElement | null>(null)
const view = shallowRef<EditorView | null>(null)

function langFor(name?: string): Extension[] {
  const f = (name || '').toLowerCase()
  if (f.endsWith('.md') || f.endsWith('.markdown')) return [markdown()]
  if (f.endsWith('.py')) return [python()]
  if (f.endsWith('.json')) return [json()]
  if (f.endsWith('.yaml') || f.endsWith('.yml')) return [yaml()]
  if (f.endsWith('.js') || f.endsWith('.ts') || f.endsWith('.jsx') || f.endsWith('.tsx')) return [javascript({ typescript: true })]
  return []
}

function build() {
  if (!host.value) return
  view.value?.destroy()
  const state = EditorState.create({
    doc: props.modelValue,
    extensions: [
      lineNumbers(), highlightActiveLine(), history(),
      keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
      ...langFor(props.filename),
      EditorView.editable.of(!props.readonly),
      EditorState.readOnly.of(!!props.readonly),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) emit('update:modelValue', u.state.doc.toString())
      }),
    ],
  })
  view.value = new EditorView({ state, parent: host.value })
}

onMounted(build)
onBeforeUnmount(() => view.value?.destroy())
// 切换文件(filename 变)或外部重置内容时重建。
watch(() => props.filename, build)
watch(() => props.modelValue, (v) => {
  if (view.value && v !== view.value.state.doc.toString()) build()
})
</script>

<template>
  <div ref="host" class="code-editor"></div>
</template>

<style scoped>
.code-editor { height: 100%; overflow: auto; font-size: 13px; }
.code-editor :deep(.cm-editor) { height: 100%; }
</style>

<template>
  <pre class="code-block"><code ref="codeRef" :class="langClass">{{ code }}</code></pre>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import scss from 'highlight.js/lib/languages/scss'
import less from 'highlight.js/lib/languages/less'
import json from 'highlight.js/lib/languages/json'
import yaml from 'highlight.js/lib/languages/yaml'
import bash from 'highlight.js/lib/languages/bash'
import python from 'highlight.js/lib/languages/python'
import markdown from 'highlight.js/lib/languages/markdown'
import 'highlight.js/styles/atom-one-light.css'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('ts', typescript)
hljs.registerLanguage('xml', xml)    // 也支持 html / vue 模板片段
hljs.registerLanguage('html', xml)
hljs.registerLanguage('vue', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('scss', scss)
hljs.registerLanguage('less', less)
hljs.registerLanguage('json', json)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('yml', yaml)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('md', markdown)

const props = defineProps<{
  code: string
  filePath?: string
  lang?: string
}>()

const codeRef = ref<HTMLElement>()

function inferLang(path?: string): string {
  if (!path) return ''
  const ext = path.split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
    ts: 'typescript', tsx: 'typescript',
    vue: 'xml',     // 当 vue SFC 当 HTML 片段高亮
    html: 'html', htm: 'html',
    css: 'css', scss: 'scss', sass: 'scss', less: 'less',
    json: 'json',
    yml: 'yaml', yaml: 'yaml',
    sh: 'bash', bash: 'bash', zsh: 'bash',
    py: 'python',
    md: 'markdown', markdown: 'markdown',
  }
  return map[ext] || ''
}

const resolvedLang = computed(() => props.lang || inferLang(props.filePath))
const langClass = computed(() => resolvedLang.value ? `language-${resolvedLang.value}` : '')

async function highlight() {
  await nextTick()
  const el = codeRef.value
  if (!el) return
  // 清掉上次的 highlight 标记，让 highlightElement 能重跑
  el.removeAttribute('data-highlighted')
  try {
    hljs.highlightElement(el)
  } catch {
    /* 语言不支持就让它当普通文本，不抛错 */
  }
}

onMounted(highlight)
watch(() => props.code, highlight)
watch(() => props.filePath, highlight)
</script>

<style scoped>
.code-block {
  margin: 0;
  padding: 0;
  background: transparent;
}
.code-block :deep(code) {
  display: block;
  padding: 12px 14px;
  font-family: 'SF Mono', 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #24292e;
  background: #fafafa;
  white-space: pre;
  overflow-x: auto;
  tab-size: 2;
}
</style>

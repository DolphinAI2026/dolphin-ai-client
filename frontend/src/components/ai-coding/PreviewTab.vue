<template>
  <div class="pt-root">
    <header class="pt-bar">
      <button class="pt-gen" :disabled="loading" @click="onGenerate">
        {{ loading ? `生成中… ${chars} 字` : (html ? '重新生成原型' : '生成原型') }}
      </button>
      <span v-if="error" class="pt-err">{{ error }}</span>
      <span v-else-if="html" class="pt-hint">点原型里任意区块 → 回到左侧对话说怎么改</span>
    </header>
    <div class="pt-stage">
      <iframe
        v-if="html"
        class="pt-frame"
        sandbox="allow-scripts"
        :srcdoc="injectedHtml"
      ></iframe>
      <div v-else class="pt-empty">
        点「生成原型」基于当前需求基线生成可交互 HTML 预览
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { generatePrototype, fetchPrototypeHtml } from '@/api/prototype'

const props = defineProps<{ appId: number }>()
const emit = defineEmits<{ (e: 'select-block', label: string): void }>()

const loading = ref(false)
const chars = ref(0)
const error = ref('')
const html = ref('')
let abort: AbortController | null = null

// 注入到原型 HTML 里的点选脚本：点带 data-block 的元素 → postMessage 给父窗。
// 字符串里的结束标签必须写成 <\/script>，否则会被 Vue SFC 解析器误判为本块结束。
const SELECT_SCRIPT = `<script>
(function(){
  document.addEventListener('click', function(e){
    var el = e.target.closest('[data-block]');
    if(!el) return;
    e.preventDefault();
    parent.postMessage({ type: 'ai-coding:select', label: el.getAttribute('data-block') }, '*');
  }, true);
})();
<\/script>`

const injectedHtml = computed(() => {
  if (!html.value) return ''
  return html.value.includes('</body>')
    ? html.value.replace('</body>', SELECT_SCRIPT + '</body>')
    : html.value + SELECT_SCRIPT
})

async function onGenerate() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  chars.value = 0
  abort = new AbortController()
  try {
    await generatePrototype(
      props.appId,
      async (ev, data) => {
        if (ev === 'progress') chars.value = data?.chars ?? 0
        else if (ev === 'error') error.value = data?.message ?? '生成失败'
        else if (ev === 'prototype_ready') {
          html.value = await fetchPrototypeHtml(props.appId, data.prototype_id)
        }
      },
      abort.signal,
    )
  } catch (e: any) {
    if (e?.name !== 'AbortError') error.value = e?.message ?? '生成失败'
  } finally {
    loading.value = false
  }
}

function onMessage(e: MessageEvent) {
  if (e.data?.type === 'ai-coding:select' && typeof e.data.label === 'string') {
    emit('select-block', e.data.label)
  }
}

onMounted(() => window.addEventListener('message', onMessage))
onUnmounted(() => {
  window.removeEventListener('message', onMessage)
  abort?.abort()
})
</script>

<style scoped>
.pt-root {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.pt-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}

.pt-gen {
  background: var(--brand);
  color: #fff;
  border: 0;
  border-radius: 8px;
  padding: 8px 16px;
  cursor: pointer;
  font-size: 13px;
}

.pt-gen:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.pt-err {
  color: var(--err);
  font-size: 12px;
}

.pt-hint {
  color: var(--text-4);
  font-size: 12px;
}

.pt-stage {
  flex: 1 1 auto;
  min-height: 0;
  background: var(--surface-3);
  padding: 12px;
}

.pt-frame {
  width: 100%;
  height: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}

.pt-empty {
  display: grid;
  place-items: center;
  height: 100%;
  color: var(--text-4);
  font-size: 13px;
}
</style>

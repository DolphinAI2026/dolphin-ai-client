<!-- frontend/src/components/common/InAppBrowser.vue
     共享内嵌浏览器: 地址栏 + iframe + 刷新 + 系统浏览器兜底。
     trusted-url: 加载可信外站(apaas 真实编辑器 URL, 跨源), 不加 sandbox。
     untrusted-html: 渲染不可信 HTML(AI 设计稿), srcdoc + 仅 allow-scripts(opaque origin)。 -->
<template>
  <div class="inapp-browser">
    <div class="iab-toolbar" v-if="showAddressBar">
      <input
        v-if="mode === 'trusted-url'"
        v-model="address"
        class="iab-address"
        type="text"
        spellcheck="false"
        placeholder="输入地址"
        @keydown.enter="go"
      />
      <span v-else class="iab-name">{{ title || '预览' }}</span>
      <button class="iab-btn" :disabled="!currentSrc" @click="reload" title="刷新">刷新</button>
      <button class="iab-btn" :disabled="!externalUrl" @click="openOutside" title="用系统浏览器打开">用系统浏览器打开</button>
    </div>
    <div class="iab-body">
      <iframe
        v-if="mode === 'trusted-url' && currentSrc"
        :key="reloadKey"
        :src="currentSrc"
        class="iab-frame"
        referrerpolicy="no-referrer"
        :title="title || '内嵌浏览器'"
      />
      <iframe
        v-else-if="mode === 'untrusted-html'"
        :key="reloadKey"
        :srcdoc="srcdoc || ''"
        class="iab-frame"
        sandbox="allow-scripts allow-popups"
        referrerpolicy="no-referrer"
        :title="title || '预览'"
      />
      <div v-else class="iab-empty"><slot name="empty">无内容</slot></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { openExternal } from '@/utils/desktop'

const props = withDefaults(defineProps<{
  mode: 'trusted-url' | 'untrusted-html'
  url?: string
  srcdoc?: string
  showAddress?: boolean
  title?: string
}>(), { url: '', srcdoc: '', title: '' })

const reloadKey = ref(0)
const address = ref(props.url || '')
const currentSrc = ref(props.url || '')

const showAddressBar = computed(() => props.showAddress ?? props.mode === 'trusted-url')
// 「用系统浏览器打开」只对 trusted-url 有意义(srcdoc 无 URL 可外开)。
const externalUrl = computed(() => (props.mode === 'trusted-url' ? currentSrc.value : ''))

function normalizeUrl(u: string): string {
  const s = (u || '').trim()
  if (!s) return ''
  return /^https?:\/\//i.test(s) ? s : 'http://' + s
}
function go() {
  const u = normalizeUrl(address.value)
  if (!u) return
  address.value = u
  currentSrc.value = u
  reloadKey.value++
}
function reload() { reloadKey.value++ }
function openOutside() { if (externalUrl.value) void openExternal(externalUrl.value) }

// 父组件改 url(选别的菜单)→ 同步加载。
watch(() => props.url, (u) => {
  if (props.mode !== 'trusted-url') return
  address.value = u || ''
  currentSrc.value = u || ''
  reloadKey.value++
})
// 父组件改 srcdoc → 重挂。
watch(() => props.srcdoc, () => { if (props.mode === 'untrusted-html') reloadKey.value++ })

defineExpose({ reload })
</script>

<style scoped>
.inapp-browser { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.iab-toolbar { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-bottom: 1px solid var(--line, #e5e7eb); flex: 0 0 auto; }
.iab-address { flex: 1; min-width: 0; background: var(--surface, #fff); border: 1px solid var(--line, #e5e7eb); border-radius: 8px; color: var(--text-1, #222); font-family: ui-monospace, monospace; font-size: 12px; padding: 5px 10px; outline: none; }
.iab-address:focus { border-color: var(--brand, #2f6bff); }
.iab-name { flex: 1; font-size: 13px; color: var(--text-2, #666); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.iab-btn { font-size: 12.5px; padding: 4px 10px; border: 1px solid var(--line, #e5e7eb); border-radius: 6px; background: var(--surface, #fff); color: var(--text-2, #666); cursor: pointer; white-space: nowrap; }
.iab-btn:hover:not(:disabled) { border-color: var(--brand, #2f6bff); color: var(--brand, #2f6bff); }
.iab-btn:disabled { opacity: .5; cursor: not-allowed; }
.iab-body { flex: 1; display: flex; min-height: 0; }
.iab-frame { flex: 1; width: 100%; border: 0; display: block; background: #fff; }
.iab-empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text-3, #888); font-size: 13px; padding: 20px; text-align: center; }
</style>

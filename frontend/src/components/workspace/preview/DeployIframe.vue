<template>
  <div class="deploy-iframe">
    <div v-if="!url" class="empty">
      <p class="muted">应用尚未部署到 aPaaS 平台</p>
    </div>
    <div v-else-if="loadFailed" class="error">
      <p>无法在嵌入框内加载（可能跨域受限）</p>
      <a :href="url" target="_blank" rel="noopener noreferrer" class="builder-btn">在新窗口打开 ↗</a>
    </div>
    <iframe
      v-else
      :src="url"
      :sandbox="sandboxAttr"
      class="iframe"
      @load="onLoad"
      @error="loadFailed = true"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

const props = defineProps<{
  platformUrl: string | null
  apaasAppId: string | null
}>()

const url = computed(() => {
  if (!props.platformUrl || !props.apaasAppId) return null
  return `${props.platformUrl.replace(/\/+$/, '')}/app/${props.apaasAppId}`
})

const sandboxAttr = 'allow-same-origin allow-scripts allow-forms allow-popups'
const loadFailed = ref(false)
const loadedOnce = ref(false)

function onLoad() {
  loadedOnce.value = true
}

onMounted(() => {
  if (url.value) {
    setTimeout(() => {
      if (!loadedOnce.value) loadFailed.value = true
    }, 1500)
  }
})
</script>

<style scoped>
.deploy-iframe { height: 100%; }
.iframe { width: 100%; height: 100%; border: 0; }
.empty, .error { padding: 32px; text-align: center; color: var(--fg-muted); }
.error p { color: var(--t-warning); margin-bottom: 12px; }
.error a { display: inline-block; margin-top: 12px; }
.muted { color: var(--fg-muted); }
</style>

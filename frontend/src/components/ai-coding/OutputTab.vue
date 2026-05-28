<template>
  <div class="ot">
    <div v-if="loading" class="ot-empty">加载代码编辑器…</div>
    <div v-else-if="error" class="ot-empty">打开 IDE 失败：{{ error }} <button class="ot-retry" @click="load">重试</button></div>
    <iframe v-else-if="ideUrl" :key="ideUrl" class="ot-frame" :src="ideUrl"></iframe>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { onlineCodingApi } from '@/api/onlineCoding'
import { useThemeStore } from '@/stores/theme'

const props = defineProps<{ workspaceId: string }>()
const themeStore = useThemeStore()
const ideUrl = ref('')
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true; error.value = ''
  try {
    const r = await onlineCodingApi.getIdeUrl(props.workspaceId, themeStore.isDark ? 'dark' : 'light')
    ideUrl.value = r.ide_url
  } catch (e: any) {
    error.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.ot { height: 100%; display: flex; }
.ot-frame { flex: 1 1 auto; width: 100%; border: 0; background: #1e1e1e; }
.ot-empty { margin: auto; color: var(--text-4); font-size: 14px; }
.ot-retry { margin-left: 8px; border: 1px solid var(--line); background: transparent; color: var(--text-3); border-radius: 6px; padding: 2px 10px; cursor: pointer; }
</style>

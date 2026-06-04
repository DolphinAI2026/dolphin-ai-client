<template>
  <button class="open-lowcode-btn" :disabled="loading" :title="title" @click="onClick">
    <span aria-hidden="true">🔧</span> {{ loading ? '打开中…' : '打开低代码后台' }}
  </button>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { getEditorUrl } from '@/api/editorUrl'

const props = defineProps<{
  appId: number
  menuType?: string
  menuId?: string
  formId?: string | null
  title?: string
}>()

const loading = ref(false)

async function onClick() {
  loading.value = true
  try {
    const resp = await getEditorUrl(props.appId, {
      menu_type: props.menuType || '',
      menu_id: props.menuId || '',
      form_id: props.formId || '',
    })
    if (resp?.ok && resp.url) {
      window.open(resp.url, '_blank')
    } else {
      alert(resp?.message || '应用尚未部署到 aPaaS，无法打开后台')
    }
  } catch (e: any) {
    alert(`打开低代码后台失败：${e?.message || '网络错误'}`)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.open-lowcode-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; font-size: 12.5px; border-radius: 6px;
  border: 1px solid var(--t-border-soft, #d1d5db); background: var(--t-bg-soft, #f3f4f6);
  color: var(--t-text-primary, #1f2937); cursor: pointer;
}
.open-lowcode-btn:hover:not(:disabled) { background: var(--t-bg-input, #e5e7eb); }
.open-lowcode-btn:disabled { opacity: .6; cursor: default; }
</style>

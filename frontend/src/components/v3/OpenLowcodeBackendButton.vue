<template>
  <button class="open-lowcode-btn" :disabled="loading" :title="title" @click="onClick">
    <AppIcon name="wrench" :size="14" /> {{ loading ? '打开中…' : '打开低代码后台' }}
  </button>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { getEditorUrl } from '@/api/editorUrl'
import AppIcon from '@/components/common/AppIcon.vue'

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
      // 直链深链到真 aPaaS host（不走代理桥接）— 生产挂在 aPaaS 下已登录态免登。
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
/* 跟随全局主题 token（design-v3-tokens.css 亮/暗双版本），对齐面板里 .fbp-btn-ghost 等按钮。
   不用浅色硬 fallback —— 之前 --t-* 那套在本 app 没定义，暗色下浅底浅字几乎看不见。 */
.open-lowcode-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; font-size: 12px; border-radius: 6px;
  border: 1px solid var(--line); background: var(--surface-2);
  color: var(--text-2); cursor: pointer;
  font-family: inherit; white-space: nowrap;
  transition: color .15s, background .15s, border-color .15s;
}
.open-lowcode-btn:hover:not(:disabled) {
  color: var(--text); border-color: var(--text-3); background: var(--surface);
}
.open-lowcode-btn:disabled { opacity: .6; cursor: default; }
</style>

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
  const targetWindow = window.open('', '_blank')
  try {
    const resp = await getEditorUrl(props.appId, {
      menu_type: props.menuType || '',
      menu_id: props.menuId || '',
      form_id: props.formId || '',
    })
    if (resp?.ok && resp.url) {
      // aPaaS 原生 fn-config 的「返回/关闭」都走 $router.go(-1)。
      // 直接进子编辑器或过快自动跳转时没有可退历史，所以先打开完整应用编辑入口。
      if (targetWindow) {
        targetWindow.location.href = resp.entry_url || resp.url
      } else {
        window.open(resp.entry_url || resp.url, '_blank')
      }
    } else {
      try { targetWindow?.close() } catch { /* ignore */ }
      alert(resp?.message || '应用尚未部署到 aPaaS，无法打开后台')
    }
  } catch (e: any) {
    try { targetWindow?.close() } catch { /* ignore */ }
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  min-width: 0;
  padding: 0 12px;
  font-size: 12.5px;
  font-weight: 500;
  line-height: 1;
  border-radius: 6px;
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--text-2);
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  box-shadow: var(--sh-1, 0 1px 2px rgba(11, 27, 63, 0.04));
  transition: color .15s, background .15s, border-color .15s, box-shadow .15s;
}
.open-lowcode-btn:hover:not(:disabled) {
  color: var(--brand);
  border-color: var(--brand-ring, var(--line-focus));
  background: var(--brand-soft);
  box-shadow: none;
}
.open-lowcode-btn:focus-visible {
  outline: 2px solid var(--brand-ring, var(--line-focus));
  outline-offset: 2px;
}
.open-lowcode-btn :deep(svg) { color: var(--brand); }
.open-lowcode-btn:disabled { opacity: .6; cursor: default; }
</style>

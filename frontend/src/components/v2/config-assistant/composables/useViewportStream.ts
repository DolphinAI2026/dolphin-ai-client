// frontend/src/components/v2/config-assistant/composables/useViewportStream.ts
//
// 2026-05-21 Phase 3d Browser viewport mini preview MJPEG 流封装.
// 2026-05-24 从 ConfigAssistantPanel.vue 抽出 (refactor #9).
//
// MJPEG 流: <img> 直接消费 multipart/x-mixed-replace, 浏览器原生解码自动播放.
// 默认收起 (不主动消费 bandwidth), 用户点 "显示 AI 浏览器画面" 展开.

import { computed, ref, type Ref } from 'vue'
import { API_PREFIX } from '@/utils/request'

export function useViewportStream(applicationId: Ref<number | undefined>) {
  const viewportEnabled = ref<boolean>(false)

  const viewportStreamUrl = computed(() => {
    if (!viewportEnabled.value || !applicationId.value) return ''
    // 加 timestamp 防 cache (MJPEG header 决定流不会真 cache 但 query param 保证 fresh)
    return `${API_PREFIX}/applications/${applicationId.value}/browser-stream?t=${Date.now()}`
  })

  function openViewportFull() {
    if (!viewportStreamUrl.value) return
    try {
      const w = window.open()
      if (w) w.document.write(`<img src="${viewportStreamUrl.value}" style="max-width:100%;height:auto;" />`)
    } catch {
      // popup blocked
    }
  }

  return { viewportEnabled, viewportStreamUrl, openViewportFull }
}

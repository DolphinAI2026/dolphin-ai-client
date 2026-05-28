<template>
  <BuilderFrame :breadcrumbs="[{ label: 'AI Coding' }]">
    <template #actions>
      <span v-if="appId" class="aicoding-app-chip">应用 #{{ appId }}</span>
    </template>

    <div v-if="!appId" class="aicoding-empty">
      请带应用进入：<code>/ai-coding/&lt;appId&gt;</code>
    </div>
    <div v-else class="aicoding-shell">
      <!-- 左：对话主线（复用 SpecChatPanel：对话改需求基线 + diff 接受/弃用） -->
      <section class="aicoding-chat" :style="{ flexBasis: chatWidth + 'px' }">
        <SpecChatPanel
          ref="specChatRef"
          :app-id="appId!"
          :active-chapter="activeChapter"
          :chapter-title="chapterTitle"
          @spec-updated="onSpecUpdated"
        />
        <div class="aicoding-resizer" @mousedown="startResize"></div>
      </section>

      <!-- 右：6 Tab 工作区 -->
      <section class="aicoding-work">
        <WorkspaceTabs :key="refreshKey" :app-id="appId!" @select-block="onSelectBlock" />
      </section>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import WorkspaceTabs from '@/components/ai-coding/WorkspaceTabs.vue'
import SpecChatPanel from '@/components/v3/SpecChatPanel.vue'

const route = useRoute()
const specChatRef = ref<{ focusInput?: () => void } | null>(null)

const appId = computed<number | null>(() => {
  const raw = route.params.appId
  const n = Number(Array.isArray(raw) ? raw[0] : raw)
  // 仅接受正整数：拒掉 1.5 / NaN / 0 / 负数
  return Number.isInteger(n) && n > 0 ? n : null
})

// 左对话聚焦的章节。章节联动（SpecDesignPanel 选章 → 对话跟随）留后续切片，
// 本切片固定默认到数据模型。
const activeChapter = ref('data_model')
const chapterTitle = ref('数据模型')

// 对话改了需求基线（spec-updated）→ 重挂 WorkspaceTabs，让其中的 SpecDesignPanel 重新拉数据
const refreshKey = ref(0)
function onSpecUpdated(_sectionType: string, _sectionKey: string) {
  refreshKey.value++
}

// 在预览原型上点选某区块 → 聚焦左侧对话 + 提示。
// SpecChatPanel 暂无外部预填能力（只 expose focusInput），完整「点选自动填入对话」留后续切片。
function onSelectBlock(label: string) {
  ElMessage.info(`已选中「${label}」，在左侧对话里说要怎么改`)
  specChatRef.value?.focusInput?.()
}

const chatWidth = ref(420)
// 拖拽中若组件卸载，用它兜底移除 window 监听
let cleanupResize: (() => void) | null = null

function startResize(e: MouseEvent) {
  e.preventDefault()
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'ew-resize'
  const startX = e.clientX
  const startW = chatWidth.value
  const onMove = (ev: MouseEvent) => {
    chatWidth.value = Math.max(320, Math.min(720, startW + ev.clientX - startX))
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    cleanupResize = null
  }
  cleanupResize = onUp
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

onUnmounted(() => cleanupResize?.())
</script>

<style scoped>
.aicoding-shell {
  display: flex;
  height: 100%;
  min-height: 0;
  flex: 1 1 auto;
  overflow: hidden;
}

.aicoding-chat {
  position: relative;
  flex: 0 0 auto;
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.aicoding-resizer {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 10;
}

.aicoding-resizer:hover {
  background: var(--brand-soft-2);
}

.aicoding-work {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.aicoding-empty {
  padding: 40px;
  color: var(--text-3);
  font-size: 14px;
}

.aicoding-app-chip {
  font-size: 12px;
  color: var(--text-3);
  padding: 2px 8px;
  background: var(--surface-3);
  border-radius: 12px;
}
</style>

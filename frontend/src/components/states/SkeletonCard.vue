<!-- frontend/src/components/states/SkeletonCard.vue
     Shared skeleton loader · Phase 5 (Wave 1 完成态)
     Per design spec 08.6 章.

     Usage:
       <SkeletonCard v-if="loading" :lines="3" with-avatar with-footer :delay="200" />

     Nodes:
       - 200ms delay before render (防闪屏) — < 200ms 直接返就别 skel
       - 5s 后追加 "还在加载…" + cancel button
       - 动画: linear-gradient + background-position 水平移动 1.4s ease-in-out infinite

     Tokens 全程 var(--xxx) — dark/light 自动适配。
-->
<template>
  <div v-if="visible" class="skel-card" :class="{ 'is-slow': slow }">
    <div v-if="withAvatar" class="skel skel-avatar"></div>
    <div class="skel skel-line title" :style="{ width: '65%' }"></div>
    <div
      v-for="(w, i) in lineWidths"
      :key="i"
      class="skel skel-line"
      :style="{ width: w }"
    ></div>
    <div v-if="withFooter" class="skel-footer">
      <div class="skel skel-line footer-pill" :style="{ width: '60px', height: '18px' }"></div>
      <div class="skel skel-line footer-meta" :style="{ width: '120px' }"></div>
    </div>
    <div v-if="slow" class="skel-slow-hint">
      <span>还在加载...</span>
      <button type="button" class="skel-cancel" @click="$emit('cancel')">取消</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{
  lines?: number
  withAvatar?: boolean
  withFooter?: boolean
  delay?: number
}>(), {
  lines: 3,
  withAvatar: false,
  withFooter: false,
  delay: 200,
})

defineEmits<{
  cancel: []
}>()

const visible = ref(false)
const slow = ref(false)
let delayTimer: number | null = null
let slowTimer: number | null = null

onMounted(() => {
  // 200ms 起延迟显示，避免极快返回导致的闪屏
  delayTimer = window.setTimeout(() => {
    visible.value = true
    // 显示后再过 5s 仍未 unmount，显示 "还在加载…" + cancel
    slowTimer = window.setTimeout(() => {
      slow.value = true
    }, 5000)
  }, props.delay)
})

onBeforeUnmount(() => {
  if (delayTimer != null) window.clearTimeout(delayTimer)
  if (slowTimer != null) window.clearTimeout(slowTimer)
})

// 生成 N 行宽度（85% / 95% / 70% / 60% / 90% ...）
const lineWidths = computed(() => {
  const pool = ['90%', '95%', '70%', '85%', '60%', '88%', '78%']
  return Array.from({ length: Math.max(1, props.lines) }, (_, i) => pool[i % pool.length])
})
</script>

<style scoped>
.skel-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.skel {
  background: linear-gradient(
    90deg,
    var(--surface-2) 0%,
    var(--surface-3) 50%,
    var(--surface-2) 100%
  );
  background-size: 200% 100%;
  animation: skel-shimmer 1.4s ease-in-out infinite;
  border-radius: 4px;
}

@keyframes skel-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.skel-avatar {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  margin-bottom: 4px;
}

.skel-line {
  height: 11px;
}

.skel-line.title {
  height: 14px;
  margin-bottom: 2px;
}

.skel-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.skel-footer .footer-meta {
  margin-top: 3px;
}

.skel-slow-hint {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-3);
  font-weight: var(--fw-medium, 500);
  letter-spacing: -0.005em;
}

.skel-cancel {
  height: 26px;
  padding: 0 10px;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.skel-cancel:hover {
  border-color: var(--brand-ring);
  color: var(--brand);
  background: var(--brand-soft);
}

.skel-cancel:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}
</style>

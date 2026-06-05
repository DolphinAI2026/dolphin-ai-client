<!-- 共享图标组件 —— 模板里用 <AppIcon name="clipboard" :size="16" /> 渲染描边 SVG。
     图标词表见 @/utils/icons.ts（ICON_PATHS）。颜色继承 currentColor，大小/线宽可调。 -->
<script setup lang="ts">
import { computed } from 'vue'
import { iconSvg } from '@/utils/icons'

const props = withDefaults(defineProps<{
  name: string
  size?: number
  stroke?: number
}>(), {
  size: 16,
  stroke: 2,
})

const html = computed(() => iconSvg(props.name, props.size, props.stroke))
</script>

<template>
  <span class="app-icon" aria-hidden="true" v-html="html" />
</template>

<style scoped>
.app-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  line-height: 0;
}
</style>

<!-- frontend/src/components/states/EmptyState.vue
     Shared empty-state component · Phase 5 (Wave 1 完成态)
     Per design spec 08.4 / 09.7 章 drop-in code A.

     Usage:
       <EmptyState title="还没有应用" desc="用对话告诉睿鲸……" variant="first">
         <template #icon>
           <svg ... />
         </template>
         <template #cta>
           <el-button type="primary" @click="onCreate">+ 新建应用</el-button>
         </template>
       </EmptyState>

     Variants:
       - 'first' (default): surface-2 灰圈 — 首次进入，合法但无数据
       - 'filtered'       : warn-soft 黄圈 — 有数据但搜不到 / 过滤后空

     Tokens 全程 var(--xxx) — dark/light 自动适配；不写 hex / theme 分支。
-->
<template>
  <div class="empty-state" :class="variantClass">
    <div class="empty-mark">
      <slot name="icon" />
    </div>
    <h3>{{ title }}</h3>
    <p v-if="desc">{{ desc }}</p>
    <div v-if="$slots.cta" class="empty-cta">
      <slot name="cta" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  title: string
  desc?: string
  variant?: 'first' | 'filtered'
}>()

const variantClass = computed(() => (props.variant === 'filtered' ? 'is-filtered' : ''))
</script>

<style scoped>
.empty-state {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: 48px 32px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
}

.empty-mark {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-4);
  display: grid;
  place-items: center;
  margin: 0 auto 14px;
  transition: background 0.18s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.empty-state.is-filtered .empty-mark {
  background: var(--warn-soft);
  color: var(--warn);
}

.empty-state :deep(.empty-mark svg) {
  width: 22px;
  height: 22px;
  stroke-width: 1.5;
}

/* Allow <el-icon> inside #icon slot */
.empty-state :deep(.empty-mark .el-icon) {
  font-size: 22px;
}

.empty-state h3 {
  font-size: 14.5px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.005em;
  margin: 0 0 4px;
  line-height: 1.4;
}

.empty-state p {
  font-size: 13px;
  color: var(--text-3);
  line-height: 1.55;
  margin: 0 auto;
  max-width: 320px;
}

.empty-cta {
  margin-top: 14px;
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
}
</style>

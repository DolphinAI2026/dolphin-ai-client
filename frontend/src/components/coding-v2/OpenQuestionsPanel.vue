<template>
  <div v-if="questions.length" class="oq-wrap">
    <button class="oq-trigger" @click="expanded = !expanded">
      <span class="oq-icon">ℹ</span>
      <span class="oq-text">AI 默认假设（{{ questions.length }} 条）</span>
      <span class="oq-hint">{{ expanded ? '收起' : '查看详情' }}</span>
      <span class="oq-chevron" :class="{ open: expanded }">›</span>
    </button>

    <div v-if="expanded" class="oq-body">
      <div v-for="(q, i) in questions" :key="i" class="oq-item">
        <div class="oq-idx">Q{{ i + 1 }}</div>
        <div class="oq-content">
          <div class="oq-q">{{ q.question }}</div>
          <div class="oq-a">假设：{{ q.assumed_answer }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  questions: { question: string; assumed_answer: string }[]
}>()

const expanded = ref(false)
</script>

<style scoped>
.oq-wrap {
  border-top: 1px solid #f3f4f6;
  border-bottom: 1px solid #f3f4f6;
}

/* ── 触发行 ── */
.oq-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 20px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: background 120ms;
}
.oq-trigger:hover { background: #f9fafb; }

.oq-icon {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #dbeafe;
  color: #2563eb;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  line-height: 1;
}

.oq-text {
  font-size: 12px;
  color: #4b5563;
  font-weight: 500;
  flex: 1;
}

.oq-hint {
  font-size: 11px;
  color: #9ca3af;
}

.oq-chevron {
  font-size: 14px;
  color: #9ca3af;
  transition: transform 200ms;
  line-height: 1;
}
.oq-chevron.open { transform: rotate(90deg); }

/* ── 展开内容 ── */
.oq-body {
  padding: 0 20px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.oq-item {
  display: flex;
  gap: 10px;
  padding: 9px 12px;
  background: #f0f7ff;
  border-radius: 6px;
  border-left: 3px solid #93c5fd;
}

.oq-idx {
  font-size: 11px;
  font-weight: 700;
  color: #2563eb;
  min-width: 22px;
  padding-top: 1px;
  flex-shrink: 0;
}

.oq-content { flex: 1; display: flex; flex-direction: column; gap: 3px; }

.oq-q {
  font-size: 12px;
  color: #1e3a5f;
  line-height: 1.55;
  font-weight: 500;
}

.oq-a {
  font-size: 12px;
  color: #4b5563;
  line-height: 1.5;
}
</style>

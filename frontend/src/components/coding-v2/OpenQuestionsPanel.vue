<template>
  <div v-if="questions.length" class="oq-panel">
    <button class="oq-header" @click="expanded = !expanded">
      <span class="oq-icon">ℹ</span>
      <span class="oq-title">AI 默认假设（{{ questions.length }} 条）</span>
      <span class="oq-chevron">{{ expanded ? '∧' : '∨' }}</span>
    </button>
    <ul v-if="expanded" class="oq-list">
      <li v-for="(q, i) in questions" :key="i" class="oq-item">
        <div class="oq-q">{{ q.question }}</div>
        <div class="oq-a">→ {{ q.assumed_answer }}</div>
      </li>
    </ul>
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
.oq-panel {
  border-top: 1px solid #f3f4f6;
  border-bottom: 1px solid #f3f4f6;
}

.oq-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  color: #6b7280;
  font-size: 12px;
}
.oq-header:hover { background: #f9fafb; }

.oq-icon {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-style: normal;
  line-height: 1;
}

.oq-title { flex: 1; color: #4b5563; font-size: 12px; }

.oq-chevron {
  font-size: 10px;
  color: #9ca3af;
}

.oq-list {
  list-style: none;
  margin: 0;
  padding: 0 18px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.oq-item {
  padding: 8px 10px;
  background: #f8faff;
  border-radius: 6px;
  border-left: 3px solid #bfdbfe;
}

.oq-q {
  font-size: 12px;
  color: #1e3a5f;
  line-height: 1.5;
}

.oq-a {
  font-size: 11px;
  color: #4b5563;
  margin-top: 3px;
  line-height: 1.5;
}
</style>

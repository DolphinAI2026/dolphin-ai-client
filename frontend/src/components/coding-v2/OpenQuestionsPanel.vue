<template>
  <div v-if="questions.length" class="open-questions">
    <div class="header">
      <span class="icon">⚠️</span>
      <span class="title">默认假设（{{ questions.length }} 条）</span>
      <button class="toggle-btn" @click="expanded = !expanded">
        {{ expanded ? '收起' : '展开' }}
      </button>
    </div>
    <ul v-if="expanded" class="list">
      <li v-for="(q, i) in questions" :key="i">
        <div class="q"><span class="q-idx">Q{{ i + 1 }}.</span> {{ q.question }}</div>
        <div class="a">→ 假设：{{ q.assumed_answer }}</div>
      </li>
    </ul>
    <div v-else class="collapsed-hint">
      brainstorm 在这些问题上替用户做了默认决定。点击"展开"查看，或在下方对话里追问
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
.open-questions {
  border: 1px solid #fde68a;
  background: #fffbeb;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 13px;
}
.header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.icon { font-size: 14px; }
.title { flex: 1; color: #92400e; font-weight: 500; }
.toggle-btn {
  background: transparent;
  border: 1px solid #f59e0b;
  color: #92400e;
  padding: 2px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.toggle-btn:hover { background: #fef3c7; }
.list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
}
.list li {
  padding: 6px 0;
  border-top: 1px dashed #fde68a;
}
.list li:first-child { border-top: none; }
.q { color: #92400e; }
.q-idx { font-weight: 600; margin-right: 4px; }
.a { color: #78350f; margin-top: 2px; margin-left: 20px; font-size: 12px; }
.collapsed-hint {
  margin-top: 4px;
  color: #b45309;
  font-size: 12px;
}
</style>

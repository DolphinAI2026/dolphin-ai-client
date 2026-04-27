<template>
  <div v-if="questions.length" class="oq-wrap">
    <button class="oq-trigger" @click="expanded = !expanded">
      <IconWarn class="oq-icon" />
      <span class="oq-text">AI 默认假设（{{ questions.length }} 条）</span>
      <span class="oq-hint">{{ expanded ? '收起' : '查看详情' }}</span>
      <span class="oq-chevron" :class="{ open: expanded }">›</span>
    </button>

    <div v-if="expanded" class="oq-body">
      <div class="oq-callout">
        以下是 AI 基于需求<strong>自动推断</strong>的开发方向，<strong>可能与真实意图不一致</strong>。请逐条核对；若有偏差，在下方聊天框<strong>直接说明调整</strong>。
      </div>
      <div v-for="(q, i) in questions" :key="i" class="oq-item">
        <div class="oq-idx">Q{{ i + 1 }}</div>
        <div class="oq-content">
          <div class="oq-q">{{ q.question }}</div>
          <div class="oq-a"><span class="oq-a-label">假设</span>{{ q.assumed_answer }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import IconWarn from './icons/IconWarn.vue'

defineProps<{
  questions: { question: string; assumed_answer: string }[]
}>()

// 默认展开 —— AI 假设对用户决策有重要参考价值，放出来比收起好
const expanded = ref(true)
</script>

<style scoped>
/* 用 amber (琥珀) 色调作为"需要用户确认"的视觉提示：
   - 比红色柔和（不是错误，只是"需复核"）
   - 比蓝色警觉（蓝色意味"提示信息"，语义不够强）
   - 左侧一条粗色条 + 淡色背景，一眼能看出这块区域"要用户动作" */
.oq-wrap {
  background: #fffbeb;
  border-radius: 8px;
  margin: 8px 0;
}

/* ── 触发行 ── */
.oq-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 20px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: background 120ms;
}
.oq-trigger:hover { background: rgba(245, 158, 11, 0.08); }

.oq-icon {
  width: 18px;
  height: 18px;
  color: #f59e0b;
  flex-shrink: 0;
}

.oq-text {
  font-size: 14px;
  color: #78350f;  /* 深琥珀：比标题灰更暖、吸引注意 */
  font-weight: 700;
  flex: 1;
}

.oq-hint {
  font-size: 11px;
  color: #b45309;
}

.oq-chevron {
  font-size: 14px;
  color: #b45309;
  transition: transform 200ms;
  line-height: 1;
}
.oq-chevron.open { transform: rotate(90deg); }

/* ── 展开内容 ── */
.oq-body {
  padding: 0 20px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 顶部一行 callout：显式说"可能和你要的不一样，请核对" */
.oq-callout {
  font-size: 12px;
  line-height: 1.6;
  color: #78350f;
  padding: 10px 12px;
  background: rgba(245, 158, 11, 0.12);
  border-radius: 4px;
}
.oq-callout strong {
  color: #92400e;
  font-weight: 600;
}

.oq-item {
  display: flex;
  gap: 12px;
  padding: 4px 0;
  /* 列表项本身不再加框，依靠外层的 amber 色调统一视觉 */
  /* Q{n} 序号与整块 content（问题 + 假设两行）在垂直方向上居中对齐 */
  align-items: center;
}

.oq-idx {
  font-size: 14px;
  font-weight: 700;
  color: #b45309;
  min-width: 28px;
  flex-shrink: 0;
}

.oq-content { flex: 1; display: flex; flex-direction: column; gap: 3px; }

.oq-q {
  font-size: 13px;
  color: #111827;
  line-height: 1.55;
  font-weight: 600;
}

.oq-a {
  font-size: 12px;
  color: #4b5563;
  line-height: 1.6;
}

.oq-a-label {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  color: #b45309;
  background: rgba(245, 158, 11, 0.15);
  padding: 1px 6px;
  border-radius: 3px;
  margin-right: 6px;
  line-height: 1.4;
  vertical-align: middle;
}
</style>

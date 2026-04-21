<template>
  <div class="chat-flow" ref="containerRef">
    <!-- 空状态 -->
    <div v-if="store.chatMessages.length === 0" class="empty-state">
      <div class="empty-icon">🚀</div>
      <h3>开始一个新需求</h3>
      <p>在下方输入框描述你要做什么，AI 会通过结构化对话帮你理清楚，然后生成代码。</p>
    </div>

    <template v-for="msg in store.chatMessages" :key="msg.id">
      <!-- ── 用户消息 ── -->
      <div v-if="msg.kind === 'user'" class="row row-user">
        <div class="bubble bubble-user">{{ msg.text }}</div>
        <div class="avatar avatar-user">👤</div>
      </div>

      <!-- ── 反问（ask-user）历史 ── -->
      <div v-else-if="msg.kind === 'ask-user'" class="row row-agent">
        <div class="avatar avatar-agent">🤖</div>
        <div class="ask-history-card" :class="getBubble(msg.bubbleId)?.answered ? 'answered' : 'pending'">
          <div class="ask-q">{{ getBubble(msg.bubbleId)?.question }}</div>
          <div v-if="getBubble(msg.bubbleId)?.answered" class="ask-ans">
            <span class="ans-label">你回答：</span>
            <span class="ans-text">{{ getBubble(msg.bubbleId)?.answer }}</span>
          </div>
          <div v-else class="ask-waiting">等待中...</div>
        </div>
      </div>

      <!-- ── 阶段分割线 ── -->
      <div v-else-if="msg.kind === 'phase-divider'" class="phase-divider">
        <span class="divider-label">{{ msg.phaseLabel }}</span>
      </div>

      <!-- ── Spec 预览 ── -->
      <div v-else-if="msg.kind === 'spec-ready'" class="full-card">
        <SpecPreview
          v-if="store.currentSpec"
          :envelope="store.currentSpec"
          :allow-actions="store.phase === 'confirm'"
          @confirm="$emit('confirmSpec')"
          @cancel="$emit('cancelSpec')"
        />
        <div v-else class="spec-loading">
          <div class="spinner"></div>
          <span>正在加载 Spec...</span>
        </div>
      </div>

      <!-- ── 代码生成进行中 ── -->
      <div v-else-if="msg.kind === 'coding-active'" class="full-card">
        <CodingProgress
          :tool-traces="store.toolTraces.filter(t => t.agent === 'coding')"
          :files="store.filesWritten"
          :streamed-text="store.streamedText"
        />
      </div>

      <!-- ── 完成 ── -->
      <div v-else-if="msg.kind === 'done'" class="full-card done-card">
        <div class="done-header">
          <span class="done-icon">🎉</span>
          <div>
            <div class="done-title">完成！</div>
            <div v-if="store.lastVerificationReport" class="done-sub">
              {{ store.lastVerificationReport.passed_count }} /
              {{ store.lastVerificationReport.items.length }} 条验收点通过
            </div>
          </div>
        </div>
        <button
          v-if="store.workspaceId"
          class="ide-btn"
          @click="$emit('openIde')"
        >
          🖥️ 打开 IDE
        </button>
        <VerificationReportPanel
          v-if="store.lastVerificationReport"
          :report="store.lastVerificationReport"
        />
      </div>

      <!-- ── 错误 ── -->
      <div v-else-if="msg.kind === 'error'" class="full-card error-card">
        <span class="error-icon">💥</span>
        <div>
          <div class="error-title">执行失败</div>
          <div class="error-text">{{ msg.text }}</div>
        </div>
      </div>

      <!-- ── 迭代 banner ── -->
      <div v-else-if="msg.kind === 'iteration'" class="iteration-banner" :class="'iter-' + msg.level">
        <span class="iter-icon">{{ iterIcon(msg.level) }}</span>
        <div class="iter-body">
          <span class="iter-level">{{ iterLabel(msg.level) }}</span>
          <span class="iter-rationale">{{ msg.rationale }}</span>
        </div>
        <span v-if="msg.confidence" class="iter-conf">{{ Math.round((msg.confidence || 0) * 100) }}%</span>
      </div>
    </template>

    <!-- 底部锚点，滚动到这里 -->
    <div ref="bottomRef" style="height: 1px;" />
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useCodingV2Store } from '@/stores/codingV2'
import type { AskUserBubble } from '@/stores/codingV2'
import CodingProgress from './CodingProgress.vue'
import SpecPreview from './SpecPreview.vue'
import VerificationReportPanel from './VerificationReportPanel.vue'

defineEmits<{
  (e: 'confirmSpec'): void
  (e: 'cancelSpec'): void
  (e: 'openIde'): void
}>()

const store = useCodingV2Store()
const containerRef = ref<HTMLElement>()
const bottomRef = ref<HTMLElement>()

function getBubble(id?: string): AskUserBubble | undefined {
  if (!id) return undefined
  return store.askUserBubbles.find((b) => b.id === id)
}

// 自动滚到底部：消息增加 or 思考文本更新
async function scrollToBottom() {
  await nextTick()
  bottomRef.value?.scrollIntoView({ behavior: 'smooth' })
}

watch(() => store.chatMessages.length, scrollToBottom)
watch(() => store.streamedText, scrollToBottom)
watch(() => store.toolTraces.length, scrollToBottom)

// 迭代 banner 辅助
function iterIcon(level?: string): string {
  switch (level) {
    case 'trivial': return '⚡'
    case 'patch': return '🔧'
    case 'rewrite': return '🔄'
    case 'cross_scene': return '⚠️'
    default: return 'ℹ️'
  }
}
function iterLabel(level?: string): string {
  switch (level) {
    case 'trivial': return '小幅修改'
    case 'patch': return '补丁迭代'
    case 'rewrite': return '重新生成'
    case 'cross_scene': return '跨场景警告'
    default: return '迭代'
  }
}
</script>

<style scoped>
.chat-flow {
  flex: 1;
  overflow-y: auto;
  padding: 24px 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ── 空状态 ── */
.empty-state {
  margin: auto;
  text-align: center;
  max-width: 400px;
  padding: 40px 24px;
  color: #6b7280;
}
.empty-icon { font-size: 48px; margin-bottom: 12px; }
.empty-state h3 { color: #111827; margin: 0 0 8px; font-size: 18px; }
.empty-state p { font-size: 14px; line-height: 1.6; margin: 0; }

/* ── 消息行 ── */
.row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 0 20px;
}
.row-user { flex-direction: row-reverse; }
.row-agent { flex-direction: row; }

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.avatar-user { background: #dbeafe; }
.avatar-agent { background: #f3f4f6; }

.bubble {
  max-width: 72%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble-user {
  background: #3b82f6;
  color: white;
  border-bottom-right-radius: 4px;
}

/* ── ask-user 历史卡片 ── */
.ask-history-card {
  max-width: 72%;
  background: white;
  border: 1px solid #e5e7eb;
  border-left: 3px solid #8b5cf6;
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ask-history-card.answered { border-left-color: #10b981; }
.ask-q {
  font-size: 13px;
  font-weight: 500;
  color: #111827;
}
.ask-ans { font-size: 13px; }
.ans-label { color: #6b7280; margin-right: 4px; }
.ans-text { color: #065f46; font-weight: 500; }
.ask-waiting { font-size: 12px; color: #9ca3af; }

/* ── 阶段分割线 ── */
.phase-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 20px;
}
.phase-divider::before,
.phase-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #e5e7eb;
}
.divider-label {
  font-size: 12px;
  color: #6b7280;
  white-space: nowrap;
  padding: 2px 10px;
  background: #f9fafb;
  border-radius: 999px;
  border: 1px solid #e5e7eb;
}

/* ── 全宽卡片（spec / coding / done / error） ── */
.full-card {
  margin: 4px 20px;
}

/* ── 完成卡 ── */
.done-card {
  background: white;
  border: 1px solid #d1fae5;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.done-header {
  display: flex;
  align-items: center;
  gap: 14px;
}
.done-icon { font-size: 32px; }
.done-title { font-size: 16px; font-weight: 600; color: #065f46; }
.done-sub { font-size: 13px; color: #6b7280; margin-top: 2px; }
.ide-btn {
  align-self: flex-start;
  padding: 8px 20px;
  border-radius: 8px;
  background: #10b981;
  color: white;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
}
.ide-btn:hover { background: #059669; }

/* ── 错误卡 ── */
.error-card {
  background: #fff1f2;
  border: 1px solid #fecdd3;
  border-radius: 12px;
  padding: 16px 20px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.error-icon { font-size: 24px; }
.error-title { font-size: 14px; font-weight: 600; color: #be123c; margin-bottom: 4px; }
.error-text { font-size: 13px; color: #9f1239; }

/* ── Spec 加载中 ── */
.spec-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  color: #6b7280;
  font-size: 14px;
}
.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid #e5e7eb;
  border-top-color: #8b5cf6;
  border-radius: 50%;
  animation: spin 800ms linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── 迭代 banner ── */
.iteration-banner {
  margin: 0 20px;
  padding: 10px 14px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  background: #fef9c3;
  border: 1px solid #fde68a;
  color: #92400e;
}
.iter-trivial { background: #f0fdf4; border-color: #bbf7d0; color: #065f46; }
.iter-patch { background: #eff6ff; border-color: #bfdbfe; color: #1d4ed8; }
.iter-rewrite { background: #fef3c7; border-color: #fde68a; color: #92400e; }
.iter-cross_scene { background: #fff7ed; border-color: #fed7aa; color: #c2410c; }
.iter-icon { font-size: 16px; flex-shrink: 0; }
.iter-body { flex: 1; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.iter-level { font-weight: 600; }
.iter-rationale { opacity: 0.85; }
.iter-conf {
  font-size: 11px;
  background: rgba(0,0,0,0.08);
  padding: 2px 6px;
  border-radius: 999px;
  flex-shrink: 0;
}
</style>

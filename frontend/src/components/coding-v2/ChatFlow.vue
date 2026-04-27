<template>
  <div class="chat-flow" ref="containerRef">
    <!-- 空状态 -->
    <div v-if="store.chatMessages.length === 0 && !store.isRunning" class="empty-state">
      <div class="empty-icon">🚀</div>
      <h3>开始一个新需求</h3>
      <p>在下方输入框描述你要做什么，AI 会通过结构化对话帮你理清楚，然后生成代码。</p>
    </div>

    <template v-for="msg in store.chatMessages" :key="msg.id">

      <!-- ── 用户消息 ── -->
      <div v-if="msg.kind === 'user'" class="row row-user">
        <div class="bubble bubble-user">{{ msg.text }}</div>
      </div>

      <!-- ── 反问历史（只显示问题，不显示回答，回答在用户气泡里） ── -->
      <div v-else-if="msg.kind === 'ask-user'" class="row row-agent">
        <div class="bubble bubble-agent">
          <div class="ask-q">{{ getBubble(msg.bubbleId)?.question }}</div>
          <div v-if="getBubble(msg.bubbleId)?.answered" class="ask-answered-badge">✓ 已回答</div>
        </div>
      </div>

      <!-- ── 阶段分割线 ── -->
      <div v-else-if="msg.kind === 'phase-divider'" class="phase-divider">
        <span class="divider-label">{{ msg.phaseLabel }}</span>
      </div>

      <!-- ── Spec 版本卡（每个版本一张，永远只有最新一张可点确认） ── -->
      <div v-else-if="msg.kind === 'spec-version'" class="full-card">
        <SpecPreview
          v-if="getCard(msg.specCardId)"
          :card-data="getCard(msg.specCardId)!"
          :latest-version="latestVersion"
          :submitting="confirmSubmitting && msg.specCardId === currentLatestId"
          :refining="store.specRefineInFlight && getCard(msg.specCardId)?.isLatest"
          @confirm="$emit('confirmSpec', $event)"
        />
        <div v-else class="spec-loading">
          <div class="spinner"></div>
          <span>正在加载 Spec...</span>
        </div>
      </div>

      <!-- ── 代码生成进行中（autofix 多轮：每张独立卡，冻结的读快照） ── -->
      <div v-else-if="msg.kind === 'coding-active'" class="full-card">
        <CodingProgress :frozen-log="msg.frozenCodingLog" />
      </div>

      <!-- ── 验收进行中（同上，冻结的读自己的快照） ── -->
      <div v-else-if="msg.kind === 'verify-active'" class="full-card">
        <VerificationProgress
          :frozen-log="msg.frozenVerifyLog"
          :frozen-report="msg.frozenVerifyReport"
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
          <button
            v-if="store.workspaceId"
            class="ide-btn"
            @click="$emit('openIde')"
          >
            🖥️ 打开 IDE
          </button>
        </div>
        <!-- 验收报告详情已由上方 verify-active 卡片展示，此处不再重复 -->
      </div>

      <!-- ── 错误 ── -->
      <div v-else-if="msg.kind === 'error'" class="full-card error-card">
        <span class="error-icon">💥</span>
        <div class="error-body">
          <div class="error-title">执行失败</div>
          <div class="error-text">{{ msg.text }}</div>
          <button
            v-if="msg.canRetry"
            class="retry-btn"
            :disabled="retrying"
            @click="$emit('retryCoding')"
          >
            {{ retrying ? '重新触发中…' : '🔄 重新生成' }}
          </button>
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

    <!-- ── Thinking 指示器：Agent 处理中且没有待答问题时显示 ── -->
    <div v-if="isThinking" class="row row-agent">
      <div class="thinking-bubble">
        <span class="dot d1" />
        <span class="dot d2" />
        <span class="dot d3" />
      </div>
    </div>

    <!-- 底部锚点 -->
    <div ref="bottomRef" style="height: 16px;" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useCodingV2Store } from '@/stores/codingV2'
import type { AskUserBubble } from '@/stores/codingV2'
import CodingProgress from './CodingProgress.vue'
import SpecPreview from './SpecPreview.vue'
import VerificationProgress from './VerificationProgress.vue'

defineProps<{
  confirmSubmitting?: boolean
  retrying?: boolean
}>()

defineEmits<{
  (e: 'confirmSpec', specId: string): void
  (e: 'openIde'): void
  (e: 'retryCoding'): void
}>()

const store = useCodingV2Store()
const containerRef = ref<HTMLElement>()
const bottomRef = ref<HTMLElement>()

function getBubble(id?: string): AskUserBubble | undefined {
  if (!id) return undefined
  return store.askUserBubbles.find((b) => b.id === id)
}

// Spec 版本卡查询：按 spec_id 找 store.specVersions 里那张
function getCard(specCardId?: string) {
  return store.getSpecCard(specCardId)
}

// 当前最新版的 version / spec_id（用于历史卡显示"被 vN 替代"、判断 confirm loading 归属）
const currentLatestId = computed<string | null>(() => store.currentSpecId)
const latestVersion = computed<number | null>(() => {
  const c = store.specVersions.find(c => c.isLatest)
  return c ? c.version : null
})

// Thinking 指示器：正在运行 且 没有待答问题 且 不是脚手架阶段（有自己的进度）
const isThinking = computed(() =>
  store.isRunning &&
  !store.pendingAskUser &&
  store.phase !== 'scaffold',
)

// 自动滚到底部
async function scrollToBottom() {
  await nextTick()
  bottomRef.value?.scrollIntoView({ behavior: 'smooth' })
}

// spec-ready 这类卡片：envelope 是 async 拉（brainstorm.spec_emitted 推 spec-ready
// 卡片时 currentSpec 还是 null，视图侧 getSpec() 回来后才渲染完整 Spec 表格）。
// 初始 scroll 在 envelope 到之前就发了，卡片撑大后会停在中间段。
// 解法：对 currentSpec / verificationReport 这类"内容后到"的状态再滚一次，
// 且用更长的延时（80ms）等 markdown / 表格子组件渲染完再滚。
async function scrollToBottomAfterRender() {
  await nextTick()
  await new Promise((r) => setTimeout(r, 80))
  bottomRef.value?.scrollIntoView({ behavior: 'smooth' })
}

watch(() => store.chatMessages.length, scrollToBottom)
watch(() => store.streamedText, scrollToBottom)
watch(() => store.toolTraces.length, scrollToBottom)
watch(isThinking, scrollToBottom)

// verify 阶段：tool_call / ac_result 追加到 store.verifyLog（不走 chatMessages）
// 之前没人 watch 它，所以验收过程整个不同步滚动。
watch(() => store.verifyLog.length, scrollToBottom)

// coding 阶段：file 写入 / tool 调用 / thinking 条目增删追加到 store.codingLog
// streamedText 只覆盖了 delta 流，非 delta 的条目（如 write_file 结束）不触发。
watch(() => store.codingLog.length, scrollToBottom)

// 异步内容：currentSpec envelope 到货（spec-ready 卡开始真正渲染）、
// lastVerificationReport 最终报告到货 —— 都要延时滚一次让表格撑开后再定位
watch(() => store.currentSpec, scrollToBottomAfterRender)
watch(() => store.lastVerificationReport, scrollToBottomAfterRender)

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
  padding: 16px 0 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* ── 空状态 ── */
.empty-state {
  margin: auto;
  text-align: center;
  max-width: 400px;
  padding: 60px 24px;
  color: #6b7280;
}
.empty-icon { font-size: 44px; margin-bottom: 16px; }
.empty-state h3 { color: #111827; margin: 0 0 10px; font-size: 18px; font-weight: 600; }
.empty-state p { font-size: 14px; line-height: 1.7; margin: 0; }

/* ── 消息行 ── */
.row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 4px 20px;
}
.row-user { flex-direction: row-reverse; }
.row-agent { flex-direction: row; }


/* ── 气泡 ── */
.bubble {
  max-width: 68%;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble-user {
  background: #3b82f6;
  color: white;
  border-radius: 18px 18px 4px 18px;
  box-shadow: 0 1px 2px rgba(59,130,246,0.3);
}
.bubble-agent {
  background: white;
  color: #111827;
  border: 1px solid #e5e7eb;
  border-radius: 18px 18px 18px 4px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ask-q {
  font-size: 14px;
  color: #1e1b4b;
  line-height: 1.55;
}
.ask-answered-badge {
  font-size: 11px;
  color: #10b981;
  display: flex;
  align-items: center;
  gap: 3px;
}

/* ── 阶段分割线 ── */
.phase-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 24px;
  margin: 4px 0;
}
.phase-divider::before,
.phase-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #e5e7eb;
}
.divider-label {
  font-size: 11px;
  color: #9ca3af;
  white-space: nowrap;
  padding: 3px 12px;
  background: #f9fafb;
  border-radius: 999px;
  border: 1px solid #e5e7eb;
  letter-spacing: 0.02em;
}

/* ── 全宽卡片 ── */
.full-card {
  margin: 6px 20px;
}

/* ── 完成卡 ── */
.done-card {
  background: white;
  border: 1px solid #d1fae5;
  border-radius: 12px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.done-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.done-icon { font-size: 28px; flex-shrink: 0; }
.done-title { font-size: 15px; font-weight: 600; color: #065f46; }
.done-sub { font-size: 12px; color: #6b7280; margin-top: 2px; }
.ide-btn {
  margin-left: auto;
  padding: 7px 16px;
  border-radius: 8px;
  background: #10b981;
  color: white;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}
.ide-btn:hover { background: #059669; }

/* ── 错误卡 ── */
.error-card {
  background: #fff1f2;
  border: 1px solid #fecdd3;
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.error-icon { font-size: 22px; flex-shrink: 0; }
.error-body { flex: 1; min-width: 0; }
.error-title { font-size: 14px; font-weight: 600; color: #be123c; margin-bottom: 4px; }
.error-text { font-size: 13px; color: #9f1239; line-height: 1.5; }
.retry-btn {
  margin-top: 10px;
  background: #be123c;
  color: white;
  border: none;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12.5px;
  cursor: pointer;
  transition: background 0.12s, opacity 0.12s;
}
.retry-btn:hover:not(:disabled) { background: #9f1239; }
.retry-btn:disabled { opacity: 0.55; cursor: not-allowed; }

/* ── Spec 加载 ── */
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

/* ── Thinking 气泡 ── */
.thinking-bubble {
  display: flex;
  gap: 5px;
  align-items: center;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 18px 18px 18px 4px;
  padding: 12px 18px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #a78bfa;
  animation: thinking 1.4s ease-in-out infinite;
}
.d1 { animation-delay: 0s; }
.d2 { animation-delay: 0.2s; }
.d3 { animation-delay: 0.4s; }
@keyframes thinking {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-5px); opacity: 1; }
}

/* ── 迭代 banner ── */
.iteration-banner {
  margin: 4px 20px;
  padding: 9px 14px;
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
.iter-icon { font-size: 15px; flex-shrink: 0; }
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

/* ── spinner ── */
.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid #e5e7eb;
  border-top-color: #8b5cf6;
  border-radius: 50%;
  animation: spin 800ms linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>

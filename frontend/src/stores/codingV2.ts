/**
 * 智能开发 V2 —— 流水线状态 store。
 *
 * 职责：
 * - 持有 conversation_id / phase / 活跃 session / Spec / VerificationReport
 * - 消费 SseClient 推来的 event，分派到各状态字段
 * - 提供计算属性给视图（应展示哪个"phase panel"）
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { IterationLevel, Phase, SceneType, SpecEnvelope } from '@/api/codingV2'
import type { SseEvent } from '@/utils/sseClient'

// ══════════════════════════════════════════════════════════════
// 面向 UI 的数据结构
// ══════════════════════════════════════════════════════════════

export interface AskUserOption {
  value: string
  label: string
}

export interface AskUserBubble {
  id: string                       // 用 seq 作为 id
  question: string
  options: AskUserOption[]
  priority: 1 | 2 | 3
  allow_free_text: boolean
  context?: string | null
  p1_key?: string | null
  ask_turn: number
  max_ask_turns: number
  answered: boolean
  answer?: string | null
}

export interface VerificationItem {
  index: number
  description: string
  status: 'pending' | 'passed' | 'failed' | 'needs_review'
  evidence: string
  confidence: number
}

export interface VerificationReport {
  report_id: string
  overall_status: 'passed' | 'failed' | 'partial' | 'pending'
  passed_count: number
  failed_count: number
  items: VerificationItem[]
  summary?: string
}

export interface IterationBanner {
  level: IterationLevel
  rationale: string
  confidence: number
  message?: string
}

export interface ToolTraceEntry {
  id: string                  // seq 作 id
  agent: string               // brainstorm / coding / verification
  tool: string
  status: 'running' | 'done' | 'error'
  timestamp: number
  summary?: string
  args_preview?: string
}

export interface FileWriteEntry {
  path: string
  action: 'create' | 'edit' | 'delete'
  summary?: string
}

// ══════════════════════════════════════════════════════════════
// Store
// ══════════════════════════════════════════════════════════════

export const useCodingV2Store = defineStore('codingV2', () => {
  // —— 身份 —— //
  const conversationId = ref<number | null>(null)
  const phase = ref<Phase>('idle')
  const activeBrainstormSessionId = ref<string | null>(null)
  const activeCodingSessionId = ref<string | null>(null)

  // —— Spec —— //
  const currentSpec = ref<SpecEnvelope | null>(null)
  const currentSpecId = ref<string | null>(null)

  // —— 事件流状态 —— //
  const askUserBubbles = ref<AskUserBubble[]>([])
  const lastIterationBanner = ref<IterationBanner | null>(null)
  const toolTraces = ref<ToolTraceEntry[]>([])
  const filesWritten = ref<FileWriteEntry[]>([])
  const lastVerificationReport = ref<VerificationReport | null>(null)

  // —— 文本流（给 MessageList 展示） —— //
  const streamedText = ref<string>('')

  // —— Workspace —— //
  const workspaceId = ref<string | null>(null)

  // —— 连接状态 —— //
  const sseConnected = ref(false)
  const sseLastError = ref<string | null>(null)

  // ══════════════════════════════════════════════════════════════
  // 计算：当前应展示的"主面板"
  // ══════════════════════════════════════════════════════════════

  const mainPanel = computed<
    'brainstorm-progress' | 'spec-preview' | 'scaffold-progress' |
    'coding-progress' | 'verification-report' | 'done' | 'failed' | 'idle'
  >(() => {
    switch (phase.value) {
      case 'idle': return 'idle'
      case 'understand': return 'brainstorm-progress'
      case 'confirm': return 'spec-preview'
      case 'scaffold': return 'scaffold-progress'
      case 'generate': return 'coding-progress'
      case 'verify': return 'verification-report'
      case 'done': return 'done'
      case 'failed': return 'failed'
      case 'aborted': return 'failed'
      default: return 'idle'
    }
  })

  const isRunning = computed(() =>
    ['understand', 'scaffold', 'generate', 'verify'].includes(phase.value),
  )

  const isAwaitingUser = computed(() =>
    ['idle', 'confirm', 'done', 'failed'].includes(phase.value),
  )

  const canSendMessage = computed(() =>
    // GENERATE/SCAFFOLD/VERIFY 时后端会 reject，但让 UI 放行并由后端反馈
    phase.value !== 'aborted',
  )

  const pendingAskUser = computed(() => {
    const items = askUserBubbles.value.filter((b) => !b.answered)
    return items.length > 0 ? items[items.length - 1] : null
  })

  const openQuestions = computed(() => currentSpec.value?.provenance?.open_questions ?? [])
  const acceptanceCriteria = computed(() => currentSpec.value?.intent?.acceptance_criteria ?? [])
  const sceneType = computed<SceneType | null>(() => currentSpec.value?.scene_type ?? null)

  // ══════════════════════════════════════════════════════════════
  // 重置
  // ══════════════════════════════════════════════════════════════

  function resetAll() {
    conversationId.value = null
    phase.value = 'idle'
    activeBrainstormSessionId.value = null
    activeCodingSessionId.value = null
    currentSpec.value = null
    currentSpecId.value = null
    askUserBubbles.value = []
    lastIterationBanner.value = null
    toolTraces.value = []
    filesWritten.value = []
    lastVerificationReport.value = null
    streamedText.value = ''
    workspaceId.value = null
    sseConnected.value = false
    sseLastError.value = null
  }

  function attachConversation(id: number) {
    if (conversationId.value !== id) resetAll()
    conversationId.value = id
  }

  // ══════════════════════════════════════════════════════════════
  // 事件分派 —— 核心逻辑
  // ══════════════════════════════════════════════════════════════

  function ingestEvent(ev: SseEvent) {
    const type = ev.type
    const data = ev.data || {}
    const seq = ev.seq

    // 1. brainstorm.*
    if (type === 'brainstorm.scene_detected') {
      // 仅观察用（实际 scene 存在 spec envelope 里）
      return
    }
    if (type === 'brainstorm.ask_user') {
      const bubble: AskUserBubble = {
        id: `ask-${seq}`,
        question: data.question || '?',
        options: (data.options || []) as AskUserOption[],
        priority: (data.priority || 2) as 1 | 2 | 3,
        allow_free_text: !!data.allow_free_text,
        context: data.context ?? null,
        p1_key: data.p1_key ?? null,
        ask_turn: data.ask_turn || 0,
        max_ask_turns: data.max_ask_turns || 5,
        answered: false,
      }
      askUserBubbles.value.push(bubble)
      return
    }
    if (type === 'brainstorm.spec_emitted') {
      currentSpecId.value = data.spec_id || null
      // envelope 由视图侧调 getSpec 拉（包含完整 JSON）
      phase.value = 'confirm'
      return
    }

    // 2. iteration.*
    if (type === 'iteration.classified') {
      lastIterationBanner.value = {
        level: data.level,
        rationale: data.rationale || '',
        confidence: Number(data.confidence) || 0,
      }
      return
    }
    if (type === 'iteration.cross_scene_warning') {
      lastIterationBanner.value = {
        level: 'cross_scene',
        rationale: data.rationale || '',
        confidence: 1,
        message: data.message || '',
      }
      return
    }
    if (type === 'iteration.trivial_patched') {
      // 带着新 spec_id，视图需重新拉 Spec
      currentSpecId.value = data.new_spec_id || currentSpecId.value
      return
    }
    if (type === 'iteration.patch_failed') {
      sseLastError.value = `trivial patch 应用失败：${data.error || 'unknown'}`
      return
    }

    // 3. coding.* — tool 调用 / 流式文本 / 文件写入
    if (type === 'coding.agent_thinking_delta' || type === 'agent_thinking_delta') {
      const delta = data.delta || data.content || ''
      streamedText.value = streamedText.value + delta
      return
    }
    if (type === 'coding.agent_tool' || type === 'agent_tool') {
      toolTraces.value.push({
        id: `tool-${seq}`,
        agent: ev.agent || 'coding',
        tool: data.tool || data.name || '?',
        status: 'running',
        timestamp: Date.now(),
        args_preview: data.args_preview || summarizeArgs(data.args),
      })
      return
    }
    if (type === 'coding.agent_result' || type === 'agent_result') {
      // 匹配最近同 tool 的 entry 标为 done
      const trace = toolTraces.value.slice().reverse().find(
        (t) => t.tool === (data.tool || data.name) && t.status === 'running',
      )
      if (trace) {
        trace.status = data.success === false ? 'error' : 'done'
        trace.summary = data.summary || data.content?.slice?.(0, 200)
      }
      // 文件写入 tool 额外记录
      if (data.tool === 'write_file' || data.tool === 'edit_file') {
        filesWritten.value.push({
          path: data.path || data.args?.path || '?',
          action: data.tool === 'write_file' ? 'create' : 'edit',
          summary: data.summary,
        })
      }
      return
    }
    if (type === 'coding.agent_done' || type === 'agent_done') {
      phase.value = 'done'
      return
    }
    if (type === 'coding.agent_error' || type === 'agent_error') {
      sseLastError.value = String(data.message || data.error || 'coding failed')
      phase.value = 'failed'
      return
    }

    // 4. verification.*
    if (type === 'verification.ac_checked') {
      // 渐进更新 last report items（若已存在）
      // MVP：只记一下，由 report_emitted 时刷全量
      return
    }
    if (type === 'verification.report_emitted') {
      lastVerificationReport.value = {
        report_id: data.report_id,
        overall_status: data.overall_status,
        passed_count: Number(data.passed_count || 0),
        failed_count: Number(data.failed_count || 0),
        items: data.items || [],
        summary: data.summary,
      }
      return
    }

    // 5. scaffold
    if (type === 'scaffold.started') {
      phase.value = 'scaffold'
      return
    }
    if (type === 'scaffold.done') {
      phase.value = 'generate'
      return
    }
    if (type === 'scaffold.failed') {
      sseLastError.value = String(data.error || 'scaffold failed')
      phase.value = 'failed'
      return
    }

    // 6. orchestrator / system
    if (type === 'orchestrator.phase_changed' || type === 'system.phase') {
      if (data.phase) phase.value = data.phase as Phase
      if (data.workspace_id) workspaceId.value = data.workspace_id
      return
    }
  }

  function summarizeArgs(args: unknown): string {
    if (args == null) return ''
    try {
      const s = typeof args === 'string' ? args : JSON.stringify(args)
      return s.length > 120 ? s.slice(0, 120) + '…' : s
    } catch {
      return ''
    }
  }

  // ══════════════════════════════════════════════════════════════
  // 用户交互辅助
  // ══════════════════════════════════════════════════════════════

  function markAskUserAnswered(bubbleId: string, answer: string) {
    const b = askUserBubbles.value.find((x) => x.id === bubbleId)
    if (b) {
      b.answered = true
      b.answer = answer
    }
  }

  function setSpec(envelope: SpecEnvelope | null) {
    currentSpec.value = envelope
    if (envelope) {
      currentSpecId.value = envelope.spec_id
    }
  }

  return {
    // state
    conversationId,
    phase,
    activeBrainstormSessionId,
    activeCodingSessionId,
    currentSpec,
    currentSpecId,
    askUserBubbles,
    lastIterationBanner,
    toolTraces,
    filesWritten,
    lastVerificationReport,
    streamedText,
    workspaceId,
    sseConnected,
    sseLastError,
    // computed
    mainPanel,
    isRunning,
    isAwaitingUser,
    canSendMessage,
    pendingAskUser,
    openQuestions,
    acceptanceCriteria,
    sceneType,
    // actions
    resetAll,
    attachConversation,
    ingestEvent,
    markAskUserAnswered,
    setSpec,
  }
})

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
// Spec 版本链（核心数据模型）
// ══════════════════════════════════════════════════════════════
//
// **架构不变量**：Spec 是一条只增不改的版本链。用户每发起一次 refine，
// 后端产出一版新 Spec（trivial patch 也好、新 brainstorm 也好），前端把它作为
// 一张新卡 push 进 chatMessages + specVersions，旧卡被标记为"已被替代"。
//
// 不要再维护"当前 Spec 单例"这种全局状态：currentSpec / currentSpecId 已降级为
// computed，从 specVersions 里找 isLatest 那张。这样：
// - UI 权限判断（"确认生成代码"是否可点）完全是卡自己的事（isLatest && !isConfirmed）
// - 并发互斥不需要额外 flag：新卡出来旧卡自动失效
// - SSE 回放按事件顺序 push，状态 = 事件流投影，无歧义
// ══════════════════════════════════════════════════════════════

export type SpecCardSource = 'brainstorm_initial' | 'brainstorm_iterate' | 'trivial_patch'

export interface SpecCardData {
  spec_id: string
  version: number                       // envelope.provenance.version（若事件未带则默认 1，envelope 到货后刷新）
  parent_version: number | null         // envelope.provenance.parent_version
  envelope: SpecEnvelope | null         // 异步拉取；null 时卡展示骨架屏
  emitted_at: number                    // 卡 push 的时间戳（毫秒）
  source: SpecCardSource
  /** 分类/反问时 LLM 给出的摘要。trivial 来自 classification.rationale；
   *  brainstorm_iterate 可为 null 或来自 emit 摘要 */
  rationale: string | null
  /** 在所有 SpecCardData 中有且只有一张 true，代表"用户可操作"的那一版。
   *  push 新卡时把其他全翻 false。 */
  isLatest: boolean
  /** 用户已点过"确认生成代码"（SSE 看到 coding.start / scaffold.started 时翻 true）。
   *  已确认的卡按钮区切换为"✓ 已用于生成代码"，禁止重复确认。 */
  isConfirmed: boolean
  /** UI 折叠状态。新卡默认展开，被替代时自动折叠。用户可手动切换。 */
  collapsed: boolean
}

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
// 代码生成时序日志（驱动 CodingProgress V1 风格渲染）
// ══════════════════════════════════════════════════════════════

export type CodingLogKind = 'thinking' | 'tool' | 'file' | 'milestone'

export interface CodingLogEntry {
  id: string
  kind: CodingLogKind
  timestamp: number
  // thinking
  text?: string
  // tool
  toolName?: string
  argsPreview?: string
  toolStatus?: 'running' | 'done' | 'error'
  filePath?: string       // write_file / edit_file 的目标路径（从 agent_tool 事件读取）
  // file（write_file / edit_file 的条目；running → done 一条用到底）
  fileAction?: 'create' | 'edit' | 'delete'
  fileContent?: string    // write/edit 的完整新内容，前端折叠展开展示
  // milestone
  milestoneText?: string
  // 通用 UI 状态：是否折叠（thinking/file 卡片共用）
  collapsed?: boolean
  // thinking 专属：aggregated 事件到达后置为 true，表示本段思考已定稿。
  // 下一条 delta 进来时若看到 sealed，应新建条目而不是继续拼接，
  // 避免"块 A 定稿后，块 B 的 delta 被追加到 A 上，aggregate B 又覆盖成 B"
  // 的视觉跳变。
  sealed?: boolean
}

// ══════════════════════════════════════════════════════════════
// 聊天流消息（统一有序消息列表，驱动 ChatFlow 渲染）
// ══════════════════════════════════════════════════════════════

export type ChatMessageKind =
  | 'user'          // 用户发出的消息
  | 'ask-user'      // brainstorm 反问（带 options）
  | 'phase-divider' // 阶段分割线
  | 'spec-version'  // 一个具体版本的 Spec 卡片（引用 specVersions 里的 spec_id）
  | 'coding-active' // 代码生成进行中（live 面板）
  | 'verify-active' // 验收进行中（逐条 AC 实时状态 + 最终报告）
  | 'done'          // 全部完成
  | 'error'         // 执行出错
  | 'iteration'     // 迭代分类 banner

export interface LiveVerifyItem {
  ac_index: number
  status: 'pending' | 'passed' | 'failed' | 'needs_review'
  confidence: number
}

// 验收流水日志（逐条展示 grep/read/check_ac 活动 + 每条 AC 结果）
export type VerifyLogKind = 'tool' | 'ac_result'
export interface VerifyLogEntry {
  id: string
  kind: VerifyLogKind
  timestamp: number
  // tool
  toolName?: string
  toolStatus?: 'running' | 'done' | 'error'
  argsPreview?: string
  // ac_result
  acIndex?: number
  acStatus?: 'pending' | 'passed' | 'failed' | 'needs_review'
  confidence?: number
}

export interface ModelOption {
  id: number
  config_name: string
  provider: string
  model: string
  is_default: boolean
}

export interface ChatMessage {
  id: string
  kind: ChatMessageKind
  timestamp: number
  // kind 专属字段（仅填对应 kind 的字段）
  text?: string         // user | error
  phase?: Phase         // phase-divider
  phaseLabel?: string   // phase-divider
  bubbleId?: string     // ask-user → 对应 askUserBubbles 中的条目
  specCardId?: string   // spec-version → 对应 specVersions 里某张卡的 spec_id
  level?: string        // iteration
  rationale?: string    // iteration
  confidence?: number   // iteration
  // error 专属
  errorReason?: string  // 'process_restart' 等，用于触发"重新生成"按钮
  canRetry?: boolean
  // coding-active / verify-active 专属：上一轮被新一轮接管时，把 live log
  // 快照进这里固化（frozen=true 的卡就只读自己的快照，不再随 store.codingLog
  // 实时变化）。这样 autofix 第 N 轮的工具步骤会在自己的卡里展示，不会和第 1
  // 轮混在一起。
  frozenCodingLog?: CodingLogEntry[]
  frozenVerifyLog?: VerifyLogEntry[]
  frozenVerifyReport?: VerificationReport | null
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

  // —— Spec 版本链 —— //
  // 按 emitted_at 升序的版本列表；旧卡永远保留（只折叠、不删）。
  const specVersions = ref<SpecCardData[]>([])

  // 向后兼容：外部调用点（apiConfirmSpec / startCodingFromSpec / 回放逻辑等）
  // 仍按"当前 Spec 单例"心智使用；computed 把它们映射到最新版卡。
  const currentSpec = computed<SpecEnvelope | null>(
    () => specVersions.value.find(c => c.isLatest)?.envelope ?? null,
  )
  const currentSpecId = computed<string | null>(
    () => specVersions.value.find(c => c.isLatest)?.spec_id ?? null,
  )

  // —— 事件流状态 —— //
  const askUserBubbles = ref<AskUserBubble[]>([])
  const lastIterationBanner = ref<IterationBanner | null>(null)
  const toolTraces = ref<ToolTraceEntry[]>([])
  const filesWritten = ref<FileWriteEntry[]>([])
  const codingLog = ref<CodingLogEntry[]>([])
  const lastVerificationReport = ref<VerificationReport | null>(null)
  // verify 实时进度（ac_checked 事件渐进追加；report_emitted 时与 lastVerificationReport 合一）
  const liveVerifyItems = ref<LiveVerifyItem[]>([])
  // verify 时序日志（driver 跑每条 AC 的工具/check 过程，类似 codingLog）
  const verifyLog = ref<VerifyLogEntry[]>([])
  // 纯视觉反馈：用户在 CONFIRM 阶段发 refine 消息、后端还没推下一版时为 true。
  // **不再用于按钮互斥**（互斥由 card.isLatest 保证）—— 只给最新卡顶部挂一个
  // "AI 正在生成新版…" 的小提示；新版到货后清零。
  const specRefineInFlight = ref(false)

  // —— 文本流（给 MessageList 展示） —— //
  const streamedText = ref<string>('')

  // —— Workspace —— //
  const workspaceId = ref<string | null>(null)

  // —— LLM 模型选择（全局三个 agent 共用） —— //
  const selectedModelId = ref<number | null>(null)
  const modelOptions = ref<ModelOption[]>([])

  // —— 连接状态 —— //
  const sseConnected = ref(false)
  const sseLastError = ref<string | null>(null)

  // —— 聊天流消息（有序列表，驱动 ChatFlow） —— //
  const chatMessages = ref<ChatMessage[]>([])

  // 待消化的 SSE 回推文本：onSend 乐观推的是 label（"Base64 编码字符串（较长）"），
  // 但后端事件里存的是 value（"base64"）。登记 value，SSE 回推同一值时跳过。
  const pendingEchoDedupe = ref<string[]>([])

  function _pushChat(msg: Omit<ChatMessage, 'timestamp'>) {
    chatMessages.value.push({ ...msg, timestamp: Date.now() })
  }

  /** 用户发送消息时，视图层调用此方法添加用户气泡
   * @param text 气泡上显示的可读文字（label）
   * @param outgoingText 实际发给后端的值（value）；与 text 不同就会登记去重
   */
  function addUserChatMessage(text: string, outgoingText?: string) {
    _pushChat({
      id: `user-${Date.now()}`,
      kind: 'user',
      text,
    })
    if (outgoingText && outgoingText !== text) {
      pendingEchoDedupe.value.push(outgoingText)
    }
  }

  /** 阶段转换时，视图层（或 ingestEvent）调用此方法插入分割线 */
  function addPhaseDivider(phase: Phase, label: string) {
    _pushChat({
      id: `pd-${phase}-${Date.now()}`,
      kind: 'phase-divider',
      phase,
      phaseLabel: label,
    })
  }

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
    specVersions.value = []
    askUserBubbles.value = []
    lastIterationBanner.value = null
    toolTraces.value = []
    filesWritten.value = []
    codingLog.value = []
    lastVerificationReport.value = null
    liveVerifyItems.value = []
    verifyLog.value = []
    specRefineInFlight.value = false
    pendingEchoDedupe.value = []
    // 模型选择在会话切换时重置，modelOptions 保留（租户级列表，不需要重拉）
    selectedModelId.value = null
    streamedText.value = ''
    workspaceId.value = null
    sseConnected.value = false
    sseLastError.value = null
    chatMessages.value = []
  }

  function attachConversation(id: number) {
    // 仅在"从一个已有对话切换到另一个"时才重置
    // null → 具体 ID（首次建对话）不应清空 chatMessages
    if (conversationId.value !== null && conversationId.value !== id) resetAll()
    conversationId.value = id
  }

  /** 用户点"重新生成"前调一次：清掉失败卡 + 旧的 active 卡 + 运行时缓存
   *
   * coding-active 也一起清掉——codingLog 是单一数据源，不清的话新一轮 coding
   * 事件会追加在旧 log 后面混杂展示。用户要看老历史可以靠回滚/另开对话。
   */
  function prepareRetry() {
    chatMessages.value = chatMessages.value.filter(
      m => m.kind !== 'error' && m.kind !== 'verify-active' && m.kind !== 'coding-active',
    )
    codingLog.value = []
    liveVerifyItems.value = []
    verifyLog.value = []
    lastVerificationReport.value = null
    sseLastError.value = null
  }

  // ══════════════════════════════════════════════════════════════
  // Spec 版本链操作
  // ══════════════════════════════════════════════════════════════

  /** 查 specVersions 里某个 spec_id 对应的卡，找不到返回 undefined */
  function getSpecCard(spec_id: string | undefined | null): SpecCardData | undefined {
    if (!spec_id) return undefined
    return specVersions.value.find(c => c.spec_id === spec_id)
  }

  /** 后端的两种"新版 Spec"事件映射到同一操作：
   *  - brainstorm.spec_emitted
   *  - iteration.trivial_patched
   *
   *  效果：上一张最新卡翻 isLatest=false 并折叠；追加新卡 isLatest=true；
   *  同步推一张 phase-divider + 一张 spec-version 消息到 chatMessages。
   *  envelope = null，由视图层 async 拉回来后调 setSpec 填入。
   *
   *  幂等：同 spec_id 重入（SSE 重放）时只更新字段，不重复 push 消息。
   */
  function pushSpecVersion(params: {
    spec_id: string
    version?: number | null
    parent_version?: number | null
    source: SpecCardSource
    rationale?: string | null
    seq: number
  }) {
    const { spec_id, source, seq } = params
    const rationale = (params.rationale ?? '').trim() || null
    const version = Number.isFinite(params.version) && params.version! > 0 ? params.version! : null
    const parent_version = Number.isFinite(params.parent_version) && params.parent_version! > 0
      ? params.parent_version!
      : null

    // 幂等：已存在同 spec_id 的卡 → 仅刷新元数据（version/rationale 来得更晚的覆盖早的）
    const existing = getSpecCard(spec_id)
    if (existing) {
      if (version != null) existing.version = version
      if (parent_version != null) existing.parent_version = parent_version
      if (rationale && !existing.rationale) existing.rationale = rationale
      return
    }

    // 1. 上一张最新卡退位
    for (const c of specVersions.value) {
      if (c.isLatest) {
        c.isLatest = false
        c.collapsed = true
      }
    }

    // 2. 推新卡
    const card: SpecCardData = {
      spec_id,
      version: version ?? (specVersions.value.length + 1),
      parent_version,
      envelope: null,
      emitted_at: Date.now(),
      source,
      rationale,
      isLatest: true,
      isConfirmed: false,
      collapsed: false,
    }
    specVersions.value.push(card)

    // 3. 推 divider + spec-version 消息（按 source 给不同文案）
    const dividerLabel = _specDividerLabel(source, card.version, parent_version, rationale)
    _pushChat({
      id: `pd-spec-${seq}`,
      kind: 'phase-divider',
      phase: 'confirm',
      phaseLabel: dividerLabel,
    })
    _pushChat({
      id: `spec-version-${seq}`,
      kind: 'spec-version',
      specCardId: spec_id,
    })

    // 4. phase 推进到 confirm（若尚未）
    phase.value = 'confirm'

    // 5. 新版到货 → 清除"正在生成新版"的纯视觉提示
    specRefineInFlight.value = false
  }

  function _specDividerLabel(
    source: SpecCardSource,
    version: number,
    parent_version: number | null,
    rationale: string | null,
  ): string {
    if (source === 'brainstorm_initial') {
      return `📋 设计方案 v${version} 已生成，请确认`
    }
    if (source === 'trivial_patch') {
      const suffix = rationale ? ` · ${_truncate(rationale, 40)}` : ''
      return `✏️ 小幅修改 v${version}${suffix}`
    }
    // brainstorm_iterate
    const parentHint = parent_version ? `（基于 v${parent_version}）` : ''
    return `🔄 重新梳理 v${version}${parentHint}`
  }

  function _truncate(s: string, max: number): string {
    return s.length > max ? s.slice(0, max) + '…' : s
  }

  /** 视图层拉到 envelope 后调：把 envelope 填到对应卡。
   *  同时根据 envelope.provenance 刷新 version / parent_version（事件未带时的兜底）。 */
  function setSpec(envelope: SpecEnvelope | null) {
    if (!envelope || !envelope.spec_id) return
    const card = getSpecCard(envelope.spec_id)
    if (!card) {
      // 极端情况：envelope 比对应的 pushSpecVersion 先到（不常见，但存在于
      // 刷新页面首次 attach 时的 warm start 场景）。补建一张卡但不推 chat 消息。
      specVersions.value.push({
        spec_id: envelope.spec_id,
        version: envelope.provenance?.version ?? 1,
        parent_version: envelope.provenance?.parent_version ?? null,
        envelope,
        emitted_at: Date.now(),
        source: 'brainstorm_initial',
        rationale: null,
        isLatest: true,
        isConfirmed: false,
        collapsed: false,
      })
      return
    }
    card.envelope = envelope
    if (envelope.provenance?.version) card.version = envelope.provenance.version
    if (envelope.provenance?.parent_version !== undefined) {
      card.parent_version = envelope.provenance.parent_version ?? null
    }
  }

  // ══════════════════════════════════════════════════════════════
  // 事件分派 —— 核心逻辑
  // ══════════════════════════════════════════════════════════════

  function ingestEvent(ev: SseEvent) {
    const type = ev.type
    const data = ev.data || {}
    const seq = ev.seq

    // Spec 下游事件到达 → 把当前最新卡标记为"已确认"（用户已点过确认按钮）。
    // 这是 per-card 状态：已确认卡的按钮区改为"✓ 已用于生成代码"，不可再点。
    // 之后 iterate 产新版时，新卡 isLatest=true + isConfirmed=false，老卡 isLatest=false
    // 但仍 isConfirmed=true —— 历史可追溯。
    if (
      type.startsWith('scaffold.') ||
      type.startsWith('coding.') ||
      type.startsWith('verification.') ||
      type === 'agent_tool' || type === 'agent_result' ||
      type === 'agent_done' || type === 'agent_error' ||
      type === 'agent_thinking_delta'
    ) {
      const latest = specVersions.value.find(c => c.isLatest)
      if (latest && !latest.isConfirmed) latest.isConfirmed = true
    }

    // 0. conversation.user_message —— SSE 回放用户消息气泡
    if (type === 'conversation.user_message') {
      const userText = String(data.text || '')
      const id = `user-evt-${seq}`
      if (chatMessages.value.some(m => m.id === id)) return
      // 回放时：如果存在未答的 ask-user 气泡，这条消息必是上一个反问的答案 → 标记已答
      const lastUnanswered = askUserBubbles.value.slice().reverse().find(b => !b.answered)
      // value → label 映射：事件里存的是 value（"base64" / "edit_read_list"），
      // 气泡该显示用户实际看到的 label（"Base64 编码字符串（较长）"）。
      // 上一个未答 ask-user 的 options 里找 value=userText 的那条，取它的 label。
      let displayText = userText
      if (lastUnanswered) {
        const opt = lastUnanswered.options.find(o => o.value === userText)
        if (opt) displayText = opt.label
        lastUnanswered.answered = true
        lastUnanswered.answer = userText
      }
      // live 去重 ①：onSend 登记过 outgoingText（label != value 的场景）
      const echoIdx = pendingEchoDedupe.value.indexOf(userText)
      if (echoIdx >= 0) {
        pendingEchoDedupe.value.splice(echoIdx, 1)
        return
      }
      // live 去重 ②：label == value（普通自由输入）场景，最近已有同文本 user 气泡
      const recent = chatMessages.value.slice(-6)
      const dupeLocal = recent.some(
        m => m.kind === 'user' && m.text === displayText && !m.id.startsWith('user-evt-'),
      )
      if (dupeLocal) return
      _pushChat({ id, kind: 'user', text: displayText })
      return
    }

    // 1. brainstorm.*
    if (type === 'brainstorm.scene_detected') {
      // 仅观察用（实际 scene 存在 spec envelope 里）
      return
    }
    if (type === 'brainstorm.ask_user') {
      const bubbleId = `ask-${seq}`
      const bubble: AskUserBubble = {
        id: bubbleId,
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
      // 聊天流：插入反问消息（问题显示在 InputBar 上方，这里仅记录已回答的历史）
      _pushChat({ id: bubbleId, kind: 'ask-user', bubbleId })
      return
    }
    if (type === 'brainstorm.spec_emitted') {
      const specId = data.spec_id
      if (!specId) return
      // 判断初始 vs 迭代：parent_version 有值 = 迭代；否则首轮。
      // 后端 `brainstorm.spec_emitted` 事件会附带 version / parent_version（若无，
      // 则 setSpec 拉到 envelope 后兜底刷新）。
      const parentVersion = Number(data.parent_version) || null
      const source: SpecCardSource = parentVersion
        ? 'brainstorm_iterate'
        : 'brainstorm_initial'
      pushSpecVersion({
        spec_id: specId,
        version: Number(data.version) || null,
        parent_version: parentVersion,
        source,
        rationale: (data.rationale || data.core_purpose || null) as string | null,
        seq,
      })
      return
    }

    // 2. iteration.*
    if (type === 'iteration.classified') {
      lastIterationBanner.value = {
        level: data.level,
        rationale: data.rationale || '',
        confidence: Number(data.confidence) || 0,
      }
      // 纯视觉反馈：最新卡顶部挂"AI 正在生成新版..."小提示。
      // 按钮互斥不靠这个，靠新版到货时 pushSpecVersion 把旧卡翻 isLatest=false。
      specRefineInFlight.value = true
      _pushChat({
        id: `iter-${seq}`,
        kind: 'iteration',
        level: data.level,
        rationale: data.rationale || '',
        confidence: Number(data.confidence) || 0,
      })
      return
    }
    if (type === 'iteration.cross_scene_warning') {
      lastIterationBanner.value = {
        level: 'cross_scene',
        rationale: data.rationale || '',
        confidence: 1,
        message: data.message || '',
      }
      // 跨场景不会产新 Spec，提示清零
      specRefineInFlight.value = false
      _pushChat({
        id: `iter-warn-${seq}`,
        kind: 'iteration',
        level: 'cross_scene',
        rationale: data.message || data.rationale || '',
        confidence: 1,
      })
      return
    }
    if (type === 'iteration.trivial_patched') {
      // 新版 Spec 作为一张新卡推进版本链。事件已带 new_spec_id + new_version；
      // parent_version 约等于"当前最新卡的 version"（后端没显式发，从前端推断）。
      const newSpecId = data.new_spec_id
      if (!newSpecId) return
      const prevLatest = specVersions.value.find(c => c.isLatest)
      pushSpecVersion({
        spec_id: newSpecId,
        version: Number(data.new_version) || null,
        parent_version: prevLatest?.version ?? null,
        source: 'trivial_patch',
        rationale: (data.rationale || null) as string | null,
        seq,
      })
      return
    }
    if (type === 'iteration.patch_failed') {
      sseLastError.value = `trivial patch 应用失败：${data.error || 'unknown'}`
      // 失败时会降级到 brainstorm minor；保留 specRefineInFlight 继续提示，
      // 等 brainstorm.spec_emitted 时由 pushSpecVersion 内部清零。
      return
    }
    if (type === 'iteration.failed') {
      sseLastError.value = `iterate 分发失败：${data.error || 'unknown'}`
      specRefineInFlight.value = false
      return
    }

    // 3. coding.* — tool 调用 / 流式文本 / 文件写入
    // coding.start — 每一轮（包括 autofix 重跑）都新造一张 coding-active 卡，上一张冻结
    if (type === 'coding.start') {
      phase.value = 'generate'
      sseLastError.value = null
      chatMessages.value = chatMessages.value.filter(m => m.kind !== 'error')
      // 找到上一张仍"活着"（没被冻结）的 coding-active，把它快照成历史
      const prevActive = chatMessages.value.slice().reverse().find(
        m => m.kind === 'coding-active' && !m.frozenCodingLog,
      )
      if (prevActive && codingLog.value.length > 0) {
        prevActive.frozenCodingLog = [...codingLog.value]
      }
      codingLog.value = []
      // 判断是第几轮：按 coding-active 数量
      const roundNum = chatMessages.value.filter(m => m.kind === 'coding-active').length + 1
      const label = roundNum === 1 ? '💻 生成代码' : `🔁 自动修复 · 第 ${roundNum} 轮`
      _pushChat({ id: `pd-generate-${seq}`, kind: 'phase-divider', phase: 'generate', phaseLabel: label })
      _pushChat({ id: `coding-active-${seq}`, kind: 'coding-active' })
      return
    }
    // Aggregated thinking（流式结束后后端发一条完整文本，落 DB 用于回放）
    if (type === 'coding.agent_thinking' || type === 'agent_thinking') {
      const fullText = String(data.content || '')
      if (!fullText) return
      const lastLog = codingLog.value[codingLog.value.length - 1]
      if (lastLog?.kind === 'thinking' && !lastLog.sealed) {
        // live 场景：刚才 delta 在这条上累积，用 aggregate 覆盖避免漂移；
        // 置 sealed=true，下一条 delta 将新开条目，不再往这条上拼。
        lastLog.text = fullText
        lastLog.sealed = true
      } else {
        // replay 场景，或前一条 thinking 已 sealed：新建条目（折叠之前的 thinking）
        for (const e of codingLog.value) {
          if (e.kind === 'thinking') e.collapsed = true
        }
        codingLog.value.push({
          id: `think-full-${seq}`,
          kind: 'thinking',
          timestamp: Date.now(),
          text: fullText,
          collapsed: false,
          sealed: true,
        })
      }
      return
    }
    if (type === 'coding.agent_thinking_delta' || type === 'agent_thinking_delta') {
      const delta = data.delta || data.content || ''
      streamedText.value = streamedText.value + delta
      // codingLog：追加到最后 *未封口* 的 thinking 条目，否则新建。
      // sealed=true 表示该条的 aggregate 已到、文本已定稿，不能再被后续
      // delta 污染（否则块 A 定稿后块 B 的 delta 会拼到 A 上造成视觉跳变）。
      const lastLog = codingLog.value[codingLog.value.length - 1]
      if (lastLog?.kind === 'thinking' && !lastLog.sealed) {
        lastLog.text = (lastLog.text || '') + delta
      } else {
        // 新 thinking 开始前，把之前所有 thinking 自动折叠；当前的默认展开
        for (const e of codingLog.value) {
          if (e.kind === 'thinking') e.collapsed = true
        }
        codingLog.value.push({
          id: `think-${seq}`,
          kind: 'thinking',
          timestamp: Date.now(),
          text: delta,
          collapsed: false,
        })
      }
      return
    }
    if (type === 'coding.agent_tool' || type === 'agent_tool') {
      const toolName = data.tool || data.name || '?'
      const preview = data.input_preview || data.args_preview || summarizeArgs(data.args)
      toolTraces.value.push({
        id: `tool-${seq}`,
        agent: ev.agent || 'coding',
        tool: toolName,
        status: 'running',
        timestamp: Date.now(),
        args_preview: preview,
      })
      // write_file / edit_file：直接作为 file 卡片（跑步/完成一条用到底），不再走 tool 行
      if (toolName === 'write_file' || toolName === 'edit_file') {
        codingLog.value.push({
          id: `file-${seq}`,
          kind: 'file',
          timestamp: Date.now(),
          toolName,                                              // 用于匹配 agent_result
          toolStatus: 'running',
          fileAction: toolName === 'write_file' ? 'create' : 'edit',
          filePath: data.input?.file_path || '?',
          fileContent: data.input?.content || '',
          collapsed: true,
        })
        return
      }
      // 其它工具（read/grep/glob/command）走 tool 行
      codingLog.value.push({
        id: `tool-${seq}`,
        kind: 'tool',
        timestamp: Date.now(),
        toolName,
        argsPreview: preview,
        toolStatus: 'running',
      })
      return
    }
    if (type === 'coding.agent_result' || type === 'agent_result') {
      const toolName = data.tool || data.name || '?'
      const trace = toolTraces.value.slice().reverse().find(
        (t) => t.tool === toolName && t.status === 'running',
      )
      if (trace) {
        trace.status = data.is_error === true ? 'error' : 'done'
        trace.summary = data.output_preview || data.summary || data.content?.slice?.(0, 200)
      }
      // write/edit：匹配最近同 tool 的 file 条目，翻到 done
      if (toolName === 'write_file' || toolName === 'edit_file') {
        const fileEntry = codingLog.value.slice().reverse().find(
          e => e.kind === 'file' && e.toolName === toolName && e.toolStatus === 'running',
        )
        if (fileEntry) {
          fileEntry.toolStatus = data.is_error === true ? 'error' : 'done'
          filesWritten.value.push({
            path: fileEntry.filePath || '?',
            action: fileEntry.fileAction || 'create',
            summary: data.output_preview || data.summary,
          })
        }
        return
      }
      // 其它工具：更新对应 tool 条目状态
      const logEntry = codingLog.value.slice().reverse().find(
        e => e.kind === 'tool' && e.toolName === toolName && e.toolStatus === 'running',
      )
      if (logEntry) {
        logEntry.toolStatus = data.is_error === true ? 'error' : 'done'
      }
      return
    }
    // 注意：BaseAgent 发 `{agent_type}.done`（即 `coding.done`），
    // 老 VibeCodingAgent adapter 发 `agent_done` / `coding.agent_done`。三者等价。
    if (type === 'coding.done' || type === 'coding.agent_done' || type === 'agent_done') {
      // 不直接 phase='done'；后续 orchestrator.phase_changed 或 verification.start 会推进到 verify
      // 只在没有 verification 链路时（首轮无 workspace 降级路径）才收尾
      return
    }
    if (type === 'coding.agent_error' || type === 'agent_error' || type === 'coding.failed') {
      const errMsg = String(data.message || data.error || 'coding failed')
      const errReason = data.reason ? String(data.reason) : ''
      sseLastError.value = errMsg
      phase.value = 'failed'
      // 注意：不要清掉 coding-active / verify-active 卡片——它们里面装着
      // 用户想回看的历史（coding 工具日志、AC 核验过程）。靠 phase='failed'
      // 让各自的 running 态停下即可（见 VerificationProgress / CodingProgress）。
      _pushChat({
        id: `error-${seq}`,
        kind: 'error',
        text: errMsg,
        errorReason: errReason,
        canRetry: errReason === 'process_restart' && !!currentSpecId.value,
      })
      return
    }

    // 4. verification.*
    if (type === 'verification.start') {
      phase.value = 'verify'
      // 把上一张仍"活着"的 verify-active 冻成历史；autofix 多轮时老卡保留可回看
      const prevActive = chatMessages.value.slice().reverse().find(
        m => m.kind === 'verify-active' && !m.frozenVerifyLog,
      )
      if (prevActive) {
        prevActive.frozenVerifyLog = [...verifyLog.value]
        prevActive.frozenVerifyReport = lastVerificationReport.value
      }
      liveVerifyItems.value = []
      verifyLog.value = []
      lastVerificationReport.value = null
      // 还停在"验收中…"的旧 divider 说明那一轮被中断了，改掉标签免得误导
      for (const m of chatMessages.value) {
        if (m.kind === 'phase-divider' && m.phase === 'verify' && m.phaseLabel?.includes('验收中')) {
          m.phaseLabel = '⚠️ 验收已中断'
        }
      }
      _pushChat({
        id: `pd-verify-${seq}`,
        kind: 'phase-divider',
        phase: 'verify',
        phaseLabel: '🧪 验收中…',
      })
      _pushChat({ id: `verify-active-${seq}`, kind: 'verify-active' })
      return
    }
    if (type === 'verification.tool_call') {
      const toolName = data.tool || '?'
      verifyLog.value.push({
        id: `vtool-${seq}`,
        kind: 'tool',
        timestamp: Date.now(),
        toolName,
        argsPreview: data.input_preview || data.args_preview || '',
        toolStatus: 'running',
      })
      return
    }
    if (type === 'verification.tool_result') {
      const toolName = data.tool || '?'
      // 匹配最近同 tool 的 running 条目，标为 done/error
      const entry = verifyLog.value.slice().reverse().find(
        e => e.kind === 'tool' && e.toolName === toolName && e.toolStatus === 'running',
      )
      if (entry) {
        entry.toolStatus = data.success === false ? 'error' : 'done'
      }
      return
    }
    if (type === 'verification.ac_checked') {
      const idx = Number(data.ac_index)
      if (!Number.isFinite(idx)) return
      const existing = liveVerifyItems.value.find(x => x.ac_index === idx)
      if (existing) {
        existing.status = data.status
        existing.confidence = Number(data.confidence) || 0
      } else {
        liveVerifyItems.value.push({
          ac_index: idx,
          status: data.status,
          confidence: Number(data.confidence) || 0,
        })
      }
      // 同步到 verifyLog，方便按时序展示
      verifyLog.value.push({
        id: `vac-${seq}`,
        kind: 'ac_result',
        timestamp: Date.now(),
        acIndex: idx,
        acStatus: data.status,
        confidence: Number(data.confidence) || 0,
      })
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
      // 把 "🧪 验收中…" 分割线翻成对应结果状态，避免卡在"验收中"字样
      const finalLabel = (() => {
        switch (data.overall_status) {
          case 'passed': return '✓ 验收通过'
          case 'failed': return '✗ 验收失败'
          case 'partial': return '⚠️ 部分通过'
          default: return '🧪 验收完成'
        }
      })()
      const verifyDivider = chatMessages.value
        .slice()
        .reverse()
        .find(m => m.kind === 'phase-divider' && m.phase === 'verify')
      if (verifyDivider) {
        verifyDivider.phaseLabel = finalLabel
      }
      // 没收到 verification.start（旧会话或跳过的路径）时，补一张 verify-active 卡片给用户看结果
      const hasActive = chatMessages.value.some(m => m.kind === 'verify-active')
      if (!hasActive) {
        _pushChat({
          id: `pd-verify-${seq}`,
          kind: 'phase-divider',
          phase: 'verify',
          phaseLabel: finalLabel,
        })
        _pushChat({ id: `verify-active-${seq}`, kind: 'verify-active' })
      }
      return
    }

    // 5. scaffold
    if (type === 'scaffold.started') {
      phase.value = 'scaffold'
      _pushChat({ id: `pd-scaffold-${seq}`, kind: 'phase-divider', phase: 'scaffold', phaseLabel: '🏗️ 搭建工作区...' })
      return
    }
    if (type === 'scaffold.done') {
      phase.value = 'generate'
      // codingLog：里程碑
      codingLog.value.push({
        id: `milestone-scaffold-${seq}`,
        kind: 'milestone',
        timestamp: Date.now(),
        milestoneText: '工程脚手架已初始化',
      })
      // 注意：不在这里推 "💻 生成代码" divider 和 coding-active 卡——
      // 否则紧接着到来的 `coding.start` handler 会误以为已经存在一轮 coding-active，
      // 把 roundNum 算成 2，divider 显示成 "🔁 自动修复 · 第 2 轮"。
      // 统一由 `coding.start` 负责推 divider + coding-active。
      return
    }
    if (type === 'scaffold.failed') {
      const errMsg = String(data.error || 'scaffold failed')
      sseLastError.value = errMsg
      phase.value = 'failed'
      _pushChat({ id: `error-scaffold-${seq}`, kind: 'error', text: errMsg })
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

  // 注意：setSpec 已在前面 Spec 版本链 section 定义（写入 specVersions 卡的 envelope）。
  // 这里不重复定义，统一用前面那个。

  return {
    // state
    conversationId,
    phase,
    activeBrainstormSessionId,
    activeCodingSessionId,
    specVersions,
    currentSpec,
    currentSpecId,
    askUserBubbles,
    lastIterationBanner,
    toolTraces,
    filesWritten,
    codingLog,
    lastVerificationReport,
    liveVerifyItems,
    verifyLog,
    specRefineInFlight,
    selectedModelId,
    modelOptions,
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
    // chat messages
    chatMessages,
    addUserChatMessage,
    addPhaseDivider,
    // actions
    resetAll,
    attachConversation,
    prepareRetry,
    ingestEvent,
    markAskUserAnswered,
    setSpec,
    pushSpecVersion,
    getSpecCard,
  }
})

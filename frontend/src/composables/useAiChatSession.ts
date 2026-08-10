/**
 * useAiChatSession — 统一 AI-chat 会话编排 composable
 *
 * 把 AIChatPage 里那套「会话 + SSE 流式 + 工具调用 + 打字动画 → AgentMessage[]」的核心逻辑
 * 抽成可复用 composable，供锁定应用上下文的右栏面板（下个任务）直接 drive，复用共享的
 * AgentConversation 渲染器。
 *
 * ⚠️ 本文件是「忠实复制」AIChatPage 的核心渲染路径（user / assistant + 流式打字 / tool 卡 /
 * ask 卡 / thinking / artifact 卡 / 每条 assistant 的 run_id），并**有意省略** AIChatPage 里
 * 与「设计文档面板 / 生成应用 CTA」强耦合的额外项（app-ready 的 #custom CTA、inline 卡片的
 * 跨段版本计数）。这些不属于通用对话渲染，面板任务用不到。
 *
 * 改动 reactivity / AgentMessage 形状时务必小心；SSE reducer 的关键漂移点由同目录 spec 锁住。
 */
import { computed, onScopeDispose, ref, type ComputedRef, type Ref } from 'vue'
import {
  aiChatApi,
  type AIChatArtifact,
  type AIChatAttachment,
  type AIChatMessage,
  type AIChatSession,
  type AIChatToolCall,
} from '@/api/aiChat'
import type { AgentAttachment, AgentMessage } from '@/components/common/agent-conversation/types'

export interface UseAiChatSessionOptions {
  /** 固定会话入口；系统助手只读取和创建自己的会话。 */
  assistantProfile?: 'entry_agent' | 'system_assistant'
  /** 固定工作模式；系统助手使用 code，但 profile 与 mode 仍保持正交。 */
  mode?: 'chat' | 'cowork' | 'code'
  /** 锁定的应用 id（建会话时带上；listSessions 也按它过滤） */
  appId?: Ref<number | null | undefined>
  /** 业务段落标识（建会话 + 每次 send 透传到后端） */
  section?: Ref<string | null | undefined>
  /** 当前视图上下文（表单/菜单名 + 设计器 tab，每次 send 透传到后端注入 app 上下文） */
  viewContext?: import('vue').Ref<string | null | undefined>
  /** 选用的 LLM 配置 id（建会话时带上） */
  selectedLlmId?: Ref<number | null | undefined>
}

export interface UseAiChatSessionReturn {
  // ── reactive state ──
  currentSession: Ref<AIChatSession | null>
  sessions: Ref<AIChatSession[]>
  agentMessages: ComputedRef<AgentMessage[]>
  artifacts: Ref<AIChatArtifact[]>
  typing: ComputedRef<boolean>
  typingSeconds: Ref<number>
  sending: Ref<boolean>
  currentRunId: Ref<string | null>
  // ── methods ──
  loadSessions: () => Promise<void>
  loadSession: (id: number) => Promise<void>
  ensureSession: () => Promise<AIChatSession>
  newSession: () => void
  send: (text: string, files?: File[]) => Promise<void>
  stop: () => Promise<void>
  dispose: () => void
}

type AiChatTransientItem =
  | { kind: 'ask'; ask: { question: string; options: string[]; tc_id: number } }
  | { kind: 'thinking'; text: string; ts: number }
  | { kind: 'artifact_card'; artifact: AIChatArtifact; ts: number }

type AiChatStreamingTool = { index: number; name: string; argumentsSoFar: string }

export interface AiChatSseReducerState {
  currentSession: Ref<AIChatSession | null>
  sessions: Ref<AIChatSession[]>
  messages: Ref<AIChatMessage[]>
  toolCalls: Ref<AIChatToolCall[]>
  artifacts: Ref<AIChatArtifact[]>
  transientItems: Ref<AiChatTransientItem[]>
  streamingText: Ref<string>
  streamingTools: Ref<Record<number, AiChatStreamingTool>>
  pendingChars: Ref<string[]>
  pendingFinalMessage: Ref<AIChatMessage | null>
  currentRunId: Ref<string | null>
  currentTurnAssistantMessageReceived: Ref<boolean>
  currentTurnFallbackErrorShown: Ref<boolean>
  ensureDrain: () => void
  flushPending: () => void
  onErrorMessage?: (message: string) => void
  onAfterEvent?: () => void
}

export function createAiChatSseReducer(state: AiChatSseReducerState) {
  return function handleSseEvent(eventName: string, data: any) {
    switch (eventName) {
      case 'user_message':
        state.messages.value.push(data)
        break
      case 'run_started':
        state.currentRunId.value = data.run_id || null
        break
      case 'thinking':
        state.transientItems.value.push({ kind: 'thinking', text: data.text || '', ts: Date.now() })
        break
      case 'assistant_delta':
        for (const ch of (data.text || '')) state.pendingChars.value.push(ch)
        state.ensureDrain()
        break
      case 'assistant_thinking_lock':
        state.flushPending()
        if (state.streamingText.value) {
          state.transientItems.value.push({ kind: 'thinking', text: state.streamingText.value, ts: Date.now() })
          state.streamingText.value = ''
        }
        break
      case 'tool_call_start': {
        state.flushPending()
        if (state.streamingText.value) {
          state.transientItems.value.push({ kind: 'thinking', text: state.streamingText.value, ts: Date.now() })
          state.streamingText.value = ''
        }
        state.streamingTools.value = {}
        const tc: AIChatToolCall = {
          id: data.id,
          session_id: state.currentSession.value?.id || 0,
          message_id: null,
          tool_name: data.tool_name,
          args_json: data.args || {},
          result_text: null,
          status: 'running',
          error_message: null,
          duration_ms: null,
          started_at: data.started_at || null,
          ended_at: null,
        }
        state.toolCalls.value.push(tc)
        break
      }
      case 'tool_call_delta': {
        const idx = data.index ?? 0
        const cur = state.streamingTools.value[idx] || { index: idx, name: '', argumentsSoFar: '' }
        if (data.name) cur.name = data.name
        if (typeof data.arguments_so_far === 'string') cur.argumentsSoFar = data.arguments_so_far
        state.streamingTools.value = { ...state.streamingTools.value, [idx]: cur }
        break
      }
      case 'tool_call_end': {
        const found = state.toolCalls.value.find(t => t.id === data.id)
        if (found) {
          found.status = data.status
          found.result_text = data.result_text
          found.duration_ms = data.duration_ms
        }
        break
      }
      case 'ask_user':
        // 信号事件：ask 卡由 collapseTools 从持久化 toolCalls.result_text 渲染（刷新后不丢）
        break
      case 'assistant_message':
        // 等 drain 把 pendingChars 排空后再展示持久化消息（让打字效果走完）
        state.currentTurnAssistantMessageReceived.value = true
        if (state.pendingChars.value.length === 0) {
          state.streamingText.value = ''
          state.messages.value.push(data)
        } else {
          state.pendingFinalMessage.value = data
        }
        break
      case 'artifact_created': {
        if (state.currentSession.value) {
          aiChatApi.listArtifacts(state.currentSession.value.id).then(d => { state.artifacts.value = d.artifacts })
        }
        break
      }
      case 'session_updated':
        if (state.currentSession.value && data.id === state.currentSession.value.id) {
          state.currentSession.value.title = data.title
          const found = state.sessions.value.find(s => s.id === data.id)
          if (found) found.title = data.title
        }
        break
      case 'error':
        {
          const message = data.error || data.message || '出错了'
          if (!state.currentTurnAssistantMessageReceived.value && !state.currentTurnFallbackErrorShown.value && state.currentSession.value) {
            state.currentTurnFallbackErrorShown.value = true
            state.messages.value.push({
              id: -Date.now(),
              session_id: state.currentSession.value.id,
              role: 'assistant',
              content: message,
              extra_meta: { local_error: true },
              created_at: new Date().toISOString(),
            })
          }
          state.transientItems.value.push({ kind: 'thinking', text: `错误：${message}`, ts: Date.now() })
          state.onErrorMessage?.(message)
        }
        break
    }
    state.onAfterEvent?.()
  }
}

export function useAiChatSession(opts?: UseAiChatSessionOptions): UseAiChatSessionReturn {
  // ── 持久化 / 服务端来源 state ──
  const currentSession = ref<AIChatSession | null>(null)
  const sessions = ref<AIChatSession[]>([])
  const messages = ref<AIChatMessage[]>([])
  const toolCalls = ref<AIChatToolCall[]>([])
  const artifacts = ref<AIChatArtifact[]>([])
  // 会话级附件(图片含 image_data_url),按 message.extra_meta.attachment_ids 映射到消息气泡。
  const attachments = ref<AIChatAttachment[]>([])

  // ── 流式 / 临时 state ──
  const sending = ref(false)
  const currentRunId = ref<string | null>(null)
  const currentAbort = ref<AbortController | null>(null)

  // 流式过程中产生但未持久化的项（ask / thinking）
  const transientItems = ref<AiChatTransientItem[]>([])

  // 当前正在流式输出的助手内容（assistant_delta 累积，经 drain 平滑释放）
  const streamingText = ref('')

  // LLM 正在流式生成 tool_calls 参数时的累积（按 index 分组）；tool_call_start 后清空
  const streamingTools = ref<Record<number, AiChatStreamingTool>>({})

  // pending 队列 + 节流：兼容「假流式」LLM（一次性吐全部）→ 按 ~80 chars/s 平滑打字
  const pendingChars = ref<string[]>([])
  let drainTimer: ReturnType<typeof setInterval> | null = null
  // 等流式 buffer 排空后才推持久化消息（避免 streaming bubble 还在打字时被抢走）
  const pendingFinalMessage = ref<AIChatMessage | null>(null)
  const currentTurnAssistantMessageReceived = ref(false)
  const currentTurnFallbackErrorShown = ref(false)

  // 「AI 思考中 Ns」计时
  const typingSeconds = ref(0)
  let secondsTimer: ReturnType<typeof setInterval> | null = null

  // ─────────────────────────────────────────────────────────────────────
  // 打字动画 drain（忠实复制 AIChatPage ensureDrain / stopDrain / flushPending）
  // ─────────────────────────────────────────────────────────────────────
  function ensureDrain() {
    if (drainTimer) return
    drainTimer = setInterval(() => {
      if (pendingChars.value.length === 0) {
        stopDrain()
        // 排空了：若有暂存的最终消息，现在落到 messages 列表
        if (pendingFinalMessage.value) {
          const m = pendingFinalMessage.value
          pendingFinalMessage.value = null
          streamingText.value = ''
          messages.value.push(m)
        }
        return
      }
      // 自适应释放速率：积压少 → 慢慢打字 (~80 chars/sec)；积压多 → 加速追上
      const rate = Math.max(2, Math.ceil(pendingChars.value.length * 0.08))
      const n = Math.min(pendingChars.value.length, rate)
      const slice = pendingChars.value.splice(0, n).join('')
      streamingText.value = streamingText.value + slice
    }, 30)
  }

  function stopDrain() {
    if (drainTimer) {
      clearInterval(drainTimer)
      drainTimer = null
    }
  }

  function flushPending() {
    if (pendingChars.value.length) {
      streamingText.value += pendingChars.value.join('')
      pendingChars.value = []
    }
    stopDrain()
  }

  function startSecondsTimer() {
    if (secondsTimer) clearInterval(secondsTimer)
    typingSeconds.value = 0
    secondsTimer = setInterval(() => {
      typingSeconds.value += 1
    }, 1000)
  }
  function stopSecondsTimer() {
    if (secondsTimer) {
      clearInterval(secondsTimer)
      secondsTimer = null
    }
    typingSeconds.value = 0
  }

  // ─────────────────────────────────────────────────────────────────────
  // 渲染辅助（忠实复制 AIChatPage 的纯函数）
  // ─────────────────────────────────────────────────────────────────────
  function toolArgsBrief(tc: AIChatToolCall): string {
    const a = tc.args_json || {}
    const textOf = (value: any): string => {
      if (value == null) return ''
      if (typeof value === 'string') return value
      if (typeof value === 'number' || typeof value === 'boolean') return String(value)
      if (typeof value === 'object' && typeof value.preview === 'string') return value.preview
      try { return JSON.stringify(value) } catch { return String(value) }
    }
    if (tc.tool_name === 'read_attachment') return textOf(a.filename)
    if (tc.tool_name === 'write_artifact') return `${textOf(a.filename)} (${textOf(a.format) || 'md'})`
    if (tc.tool_name === 'run_python') return textOf(a.code).slice(0, 60).replace(/\n/g, ' ') + '…'
    if (tc.tool_name === 'ask_clarifying_question') return textOf(a.question).slice(0, 80)
    if (tc.tool_name === 'write_file') return textOf(a.file_path)
    if (tc.tool_name === 'edit_file') return textOf(a.file_path)
    if (tc.tool_name === 'run_command') return textOf(a.command)
    return ''
  }

  function _parseToolResult(text: string | null | undefined): any | null {
    if (!text) return null
    try {
      return JSON.parse(text)
    } catch {
      return null
    }
  }

  /**
   * 按工具名 + result JSON 生成一行摘要 chip（忠实复制 AIChatPage.summarizeToolResult）。
   * status=error/aborted 时退化到 "❌ ..."；解析失败/未知工具 → 空串（ToolCard 退化到默认）。
   */
  function summarizeToolResult(name: string, status: string, resultText: string | null | undefined): string {
    if (status === 'aborted') return '已停止'
    if (status === 'error' || status === 'aborted') {
      const r = _parseToolResult(resultText) || {}
      const ec = r.error_code || r.code
      const msg = r.message || r.error || r.detail
      if (ec) return `❌ ${ec}`
      if (msg) return `❌ ${String(msg).slice(0, 60)}`
      return '❌ 调用失败'
    }
    if (status !== 'success') return ''

    const r = _parseToolResult(resultText)
    if (!r) return ''

    if (name === 'list_platform_envs') {
      const envs: any[] = Array.isArray(r.envs) ? r.envs : []
      const count = r.connected_count ?? envs.filter(e => e?.status === 'connected').length ?? envs.length
      const def = envs.find(e => e?.is_default) || envs[0]
      if (def?.name) return `✅ 找到 ${count} 个环境，默认 ${def.name}`
      return `✅ 找到 ${count} 个环境`
    }
    if (name === 'validate_builder_doc' || name === 'validate_apaas_builder_doc') {
      const errs: any[] = Array.isArray(r.errors) ? r.errors : []
      const warns: any[] = Array.isArray(r.warnings) ? r.warnings : []
      const sections = r.section_count ?? r.sections_count ?? (Array.isArray(r.sections) ? r.sections.length : null)
      if (errs.length === 0) {
        const secPart = sections != null ? `${sections} 章节 / ` : ''
        return `✅ 校验通过 ${secPart}${warns.length} warning`
      }
      return `⚠️ ${errs.length} 个错误 / ${warns.length} warning`
    }
    if (name === 'generate_app_from_doc') {
      if (r.ok === false) return '❌ 生成失败'
      const appId = r.app_id ?? r.application_id
      const appName = r.app_name || r.application_name || ''
      if (appId) return `✅ app_id=${appId}${appName ? ' ' + appName : ''}`
      return '✅ 应用已生成'
    }
    if (name === 'deploy_application') {
      if (r.ok === false) return '❌ 部署失败'
      const apaasId = r.apaas_app_id
      const st = r.status || r.deploy_status
      if (apaasId) return `✅ 部署完成 apaas_app_id=${apaasId}`
      if (st === 'pending' || st === 'running') return '🟡 后台部署中'
      return '✅ 部署完成'
    }
    if (name === 'get_application') {
      const appName = r.app_name || r.application_name || ''
      const st = r.status || r.app_status
      if (appName || st) return `应用信息已就绪${appName ? '（' + appName + (st ? ', status=' + st : '') + '）' : st ? '（status=' + st + '）' : ''}`
      return '应用信息已就绪'
    }
    if (name === 'list_my_applications' || name === 'list_applications' || name === 'list_apaas_apps' || name === 'list_apaas_apps_in_env') {
      if (r.ok === false || r.success === false) {
        const rawText = Array.isArray(r.raw?.content)
          ? r.raw.content.map((x: any) => x?.text).filter(Boolean).join('；')
          : ''
        const msg = rawText || r.message || r.error || r.detail || r.error_code
        return msg ? `❌ ${String(msg).slice(0, 60)}` : '❌ 查询应用失败'
      }
      const items: any[] = Array.isArray(r.apps) ? r.apps : Array.isArray(r.applications) ? r.applications : Array.isArray(r.items) ? r.items : []
      return `找到 ${items.length} 个应用`
    }
    if (name === 'ask_clarifying_question') {
      return '⏸️ 等待用户回答'
    }
    if (name === 'write_artifact') {
      const fname = r.filename || r.path
      const ver = r.version
      if (fname && ver != null) return `✅ ${fname} v${ver}`
      if (fname) return `✅ ${fname}`
      return '✅ 已写入设计文档'
    }
    if (name === 'read_attachment') {
      const fname = r.filename
      const lines = r.line_count ?? r.lines
      if (fname && lines != null) return `✅ 读取 ${fname} (${lines} 行)`
      if (fname) return `✅ 读取 ${fname}`
      return '✅ 已读取附件'
    }
    if (name === 'write_file') {
      const fname = r.file_path || r.path
      return fname ? `✅ ${fname}` : '✅ 文件已写入'
    }
    if (name === 'edit_file') {
      const fname = r.file_path || r.path
      return fname ? `✅ ${fname}` : '✅ 文件已编辑'
    }
    if (name === 'run_command') {
      const exitCode = r.exit_code ?? r.code ?? r.return_code
      if (exitCode != null) {
        return exitCode === 0 ? '✅ exit 0' : `❌ exit ${exitCode}`
      }
      return r.ok === true || r.success === true ? '✅ 完成' : ''
    }

    if (r.ok === true || r.success === true) return '✅ 完成'
    if (r.ok === false || r.success === false) return '❌ 失败'
    return ''
  }

  function parseAskFromResult(result_text: string | null | undefined): { question: string; options: string[] } | null {
    if (!result_text) return null
    try {
      const parsed = JSON.parse(result_text)
      if (parsed && parsed._special === 'ask_user' && typeof parsed.question === 'string') {
        return { question: parsed.question, options: Array.isArray(parsed.options) ? parsed.options : [] }
      }
    } catch {
      /* not JSON, ignore */
    }
    return null
  }

  function tsOf(s: string | null | undefined): number {
    if (!s) return 0
    const t = Date.parse(s)
    return Number.isNaN(t) ? 0 : t
  }

  // ─────────────────────────────────────────────────────────────────────
  // timeline 构建（忠实复制 AIChatPage renderTimeline + collapseTools 的核心，
  // 省略 app-ready CTA / inline 卡片跨段版本计数；artifact 卡用「最新匹配版本」简化）
  // ─────────────────────────────────────────────────────────────────────
  type TLItem =
    | { kind: 'msg'; msg: AIChatMessage }
    | { kind: 'tool'; tool: AIChatToolCall }
    | { kind: 'tool_group'; tools: AIChatToolCall[] }
    | { kind: 'ask'; ask: { question: string; options: string[]; tc_id: number } }
    | { kind: 'artifact_card'; artifact: AIChatArtifact }
    | { kind: 'thinking'; text: string; ts: number }
    | { kind: 'streaming'; text: string }

  function latestArtifact(fname: string): AIChatArtifact | null {
    const versions = artifacts.value
      .filter(a => a.filename === fname)
      .sort((a, b) => a.version - b.version)
    return versions[versions.length - 1] ?? null
  }

  // 把同名连续 ≥2 次的 tool calls 折叠成 group；段尾 write_artifact 成功 → artifact 卡；
  // 段尾 ask_clarifying_question 成功 → ask 卡（刷新后也能看到）
  function collapseTools(tcs: AIChatToolCall[]): TLItem[] {
    const out: TLItem[] = []
    let i = 0
    while (i < tcs.length) {
      const base = tcs[i]!
      let j = i + 1
      while (j < tcs.length && tcs[j]!.tool_name === base.tool_name) j++
      if (j - i >= 2) {
        out.push({ kind: 'tool_group', tools: tcs.slice(i, j) })
      } else {
        out.push({ kind: 'tool', tool: base })
      }
      const last = tcs[j - 1]
      if (last && last.tool_name === 'write_artifact' && last.status === 'success') {
        const fname = last.args_json?.filename
        if (fname) {
          const art = latestArtifact(fname)
          if (art) out.push({ kind: 'artifact_card', artifact: art })
        }
      }
      if (last && last.tool_name === 'ask_clarifying_question' && last.status === 'success') {
        const ask = parseAskFromResult(last.result_text)
        if (ask) out.push({ kind: 'ask', ask: { question: ask.question, options: ask.options, tc_id: last.id } })
      }
      i = j
    }
    return out
  }

  const renderTimeline = computed<TLItem[]>(() => {
    type Sortable =
      | { kind: 'msg'; ts: number; seq: number; msg: AIChatMessage }
      | { kind: 'tc'; ts: number; seq: number; tool: AIChatToolCall }

    const sortable: Sortable[] = []
    for (const m of messages.value) {
      sortable.push({ kind: 'msg', ts: tsOf(m.created_at), seq: m.id, msg: m })
    }
    for (const tc of toolCalls.value) {
      sortable.push({ kind: 'tc', ts: tsOf(tc.started_at), seq: tc.id, tool: tc })
    }
    sortable.sort((a, b) => {
      if (a.ts !== b.ts) return a.ts - b.ts
      if (a.kind !== b.kind) return a.kind === 'msg' ? -1 : 1
      return a.seq - b.seq
    })

    const items: TLItem[] = []
    let toolBuf: AIChatToolCall[] = []
    const flushTools = () => {
      if (!toolBuf.length) return
      for (const it of collapseTools(toolBuf)) items.push(it)
      toolBuf = []
    }
    for (const item of sortable) {
      if (item.kind === 'tc') {
        toolBuf.push(item.tool)
      } else {
        flushTools()
        items.push({ kind: 'msg', msg: item.msg })
      }
    }
    flushTools()

    for (const t of transientItems.value) items.push(t)
    if (streamingText.value) items.push({ kind: 'streaming', text: streamingText.value })
    return items
  })

  // 把 renderTimeline 映射成 AgentConversation 公共消息契约（AgentMessage[]）
  const agentMessages = computed<AgentMessage[]>(() => {
    const out: AgentMessage[] = []
    const mapStatus = (s: string): 'pending' | 'running' | 'success' | 'error' | 'aborted' =>
      (s as any) || 'pending'
    const mapTool = (tc: AIChatToolCall) => ({
      id: tc.id,
      name: tc.tool_name,
      args: tc.args_json,
      argsBrief: toolArgsBrief(tc),
      result: tc.result_text || undefined,
      resultSummary: summarizeToolResult(tc.tool_name, tc.status, tc.result_text) || undefined,
      status: mapStatus(tc.status),
      duration_ms: tc.duration_ms ?? undefined,
    })
    for (const item of renderTimeline.value) {
      if (item.kind === 'msg' && item.msg.role === 'user') {
        // 把 message.extra_meta.attachment_ids 映射成气泡里的附件(图片用 image_data_url 渲缩略图)。
        const attIds = (((item.msg as any).extra_meta?.attachment_ids) as number[] | undefined) || []
        const msgAtts: AgentAttachment[] = attIds
          .map(aid => attachments.value.find(a => a.id === aid))
          .filter((a): a is AIChatAttachment => !!a)
          .map(a => ({
            id: a.id,
            kind: a.kind === 'image' ? 'image' : 'file',
            filename: a.filename,
            url: a.image_data_url || undefined,
          }))
        out.push({
          id: 'm' + item.msg.id,
          kind: 'user',
          content: item.msg.content,
          ...(msgAtts.length ? { attachments: msgAtts } : {}),
        })
      } else if (item.kind === 'msg' && item.msg.role === 'assistant') {
        if (item.msg.content) {
          out.push({
            id: 'm' + item.msg.id,
            kind: 'assistant',
            content: item.msg.content,
            meta: (item.msg as any).run_id ? { run_id: (item.msg as any).run_id } : undefined,
          })
        }
      } else if (item.kind === 'tool') {
        out.push({ id: 't' + item.tool.id, kind: 'tool', tool: mapTool(item.tool) })
      } else if (item.kind === 'tool_group') {
        // 拆成单条 tool — AgentConversation 在 toolGrouping=true 时按需 re-group（同名连续会合并）
        for (const t of item.tools) {
          out.push({ id: 't' + t.id, kind: 'tool', tool: mapTool(t) })
        }
      } else if (item.kind === 'ask') {
        out.push({
          id: 'ask' + item.ask.tc_id,
          kind: 'ask',
          ask: { question: item.ask.question, options: item.ask.options },
        })
      } else if (item.kind === 'thinking') {
        out.push({ id: 'tk' + item.ts, kind: 'thinking', thinking: { text: item.text, locked: true } })
      } else if (item.kind === 'artifact_card') {
        out.push({
          id: 'art' + item.artifact.id,
          kind: 'artifact',
          artifact: {
            id: item.artifact.id,
            filename: item.artifact.filename,
            version: item.artifact.version,
            preview: item.artifact.preview || undefined,
            raw: item.artifact,
          },
        })
      } else if (item.kind === 'streaming') {
        out.push({ id: 'streaming', kind: 'streaming', content: item.text, streaming: true })
      }
    }
    return out
  })

  // 最后一次工具调用是 ask_clarifying_question success 且用户还没回答 → AI 在等回答
  // （忠实复制 AIChatPage.lastEventIsAsk，用于 typing 门控）
  const lastEventIsAsk = computed(() => {
    const tcs = toolCalls.value
    const last = tcs[tcs.length - 1]
    if (!last) return false
    if (last.tool_name !== 'ask_clarifying_question' || last.status !== 'success') return false
    const msgs = messages.value
    const lastMsg = msgs[msgs.length - 1]
    if (lastMsg?.role === 'user') return false
    return true
  })

  // typing 指示器门控（对齐 AIChatPage 模板：isSending && !lastEventIsAsk && !streamingText）
  const typing = computed(() => sending.value && !lastEventIsAsk.value && !streamingText.value)

  const handleSseEvent = createAiChatSseReducer({
    currentSession,
    sessions,
    messages,
    toolCalls,
    artifacts,
    transientItems,
    streamingText,
    streamingTools,
    pendingChars,
    pendingFinalMessage,
    currentRunId,
    currentTurnAssistantMessageReceived,
    currentTurnFallbackErrorShown,
    ensureDrain,
    flushPending,
  })

  // ─────────────────────────────────────────────────────────────────────
  // public methods
  // ─────────────────────────────────────────────────────────────────────
  async function loadSessions(): Promise<void> {
    const appId = opts?.appId?.value
    const params = {
      ...(appId != null ? { app_id: appId } : {}),
      ...(opts?.mode ? { mode: opts.mode } : {}),
      ...(opts?.assistantProfile ? { assistant_profile: opts.assistantProfile } : {}),
    }
    const data = await aiChatApi.listSessions(Object.keys(params).length ? params : undefined)
    sessions.value = data.sessions
  }

  async function restoreRunningSession(id: number): Promise<void> {
    try {
      const status = await aiChatApi.getRunStatus(id)
      if (!status.running || currentSession.value?.id !== id || sending.value) return

      sending.value = true
      currentRunId.value = status.run_id
      currentTurnAssistantMessageReceived.value = false
      currentTurnFallbackErrorShown.value = false
      startSecondsTimer()
      const controller = new AbortController()
      currentAbort.value = controller
      void aiChatApi.attachRun(id, status.last_seq, {
        signal: controller.signal,
        onEvent: handleSseEvent,
      }).finally(async () => {
        if (currentAbort.value !== controller) return
        stopDrain()
        stopSecondsTimer()
        sending.value = false
        currentAbort.value = null
        transientItems.value = []
        streamingText.value = ''
        currentTurnAssistantMessageReceived.value = false
        currentTurnFallbackErrorShown.value = false
        if (currentSession.value?.id === id) {
          try { await loadSession(id, false) } catch { /* keep current history */ }
        }
      })
    } catch {
      // 历史内容已经加载；恢复状态不可用时不阻断用户继续对话。
    }
  }

  async function loadSession(id: number, restoreRun = true): Promise<void> {
    // 切到不同 session 前，先 abort 进行中的 SSE，清流式临时态，避免「新会话显示旧会话尾巴」
    if (currentSession.value && currentSession.value.id !== id) {
      if (currentAbort.value) {
        try { currentAbort.value.abort() } catch { /* ignore */ }
        currentAbort.value = null
      }
      transientItems.value = []
      streamingText.value = ''
      streamingTools.value = {}
      pendingChars.value = []
      pendingFinalMessage.value = null
      stopDrain()
      stopSecondsTimer()
      sending.value = false
      currentRunId.value = null
    }
    const appId = opts?.appId?.value
    const data = await aiChatApi.getSession(id, appId != null ? { app_id: appId } : undefined)
    currentSession.value = data.session
    const sessionIndex = sessions.value.findIndex(s => s.id === data.session.id)
    if (sessionIndex >= 0) {
      sessions.value.splice(sessionIndex, 1, data.session)
    } else {
      sessions.value.unshift(data.session)
    }
    messages.value = Array.isArray(data.messages) ? data.messages : []
    toolCalls.value = Array.isArray(data.tool_calls) ? data.tool_calls : []
    artifacts.value = Array.isArray(data.artifacts) ? data.artifacts : []
    attachments.value = Array.isArray(data.attachments) ? data.attachments : []
    transientItems.value = []
    streamingText.value = ''
    if (restoreRun) void restoreRunningSession(id)
  }

  async function ensureSession(): Promise<AIChatSession> {
    if (currentSession.value) return currentSession.value
    const created = await aiChatApi.createSession({
      app_id: opts?.appId?.value ?? null,
      section: opts?.section?.value ?? null,
      selected_llm_config_id: opts?.selectedLlmId?.value ?? null,
      mode: opts?.mode,
      assistant_profile: opts?.assistantProfile,
    })
    currentSession.value = created
    // 新建会话并入列表头部（不重复）
    if (!sessions.value.some(s => s.id === created.id)) {
      sessions.value = [created, ...sessions.value]
    }
    // 全新会话：清空残留对话态
    messages.value = []
    toolCalls.value = []
    artifacts.value = []
    transientItems.value = []
    streamingText.value = ''
    currentRunId.value = null
    return created
  }

  // 重置成一个全新空会话（不发 API；下次 send 时 ensureSession 才真建）
  function newSession(): void {
    if (currentAbort.value) {
      try { currentAbort.value.abort() } catch { /* ignore */ }
      currentAbort.value = null
    }
    stopDrain()
    stopSecondsTimer()
    sending.value = false
    currentSession.value = null
    messages.value = []
    toolCalls.value = []
    artifacts.value = []
    transientItems.value = []
    streamingText.value = ''
    streamingTools.value = {}
    pendingChars.value = []
    pendingFinalMessage.value = null
    currentRunId.value = null
  }

  async function send(text: string, files?: File[]): Promise<void> {
    const msg = (text || '').trim()
    if (!msg && !(files && files.length)) return
    if (sending.value) return

    const session = await ensureSession()

    // 上传附件
    let uploadedAttIds: number[] = []
    if (files && files.length > 0) {
      const result = await aiChatApi.uploadAttachments(session.id, files)
      uploadedAttIds = result.attachments.map(a => a.id)
      // 把上传的附件(图片含 image_data_url)并入会话级附件 → live 发送时用户消息气泡立刻渲染缩略图,
      // 不必等 send 后 reload。
      for (const a of result.attachments) {
        if (!attachments.value.some(x => x.id === a.id)) attachments.value.push(a)
      }
    }

    // 发送：重置流式态
    sending.value = true
    transientItems.value = []
    streamingText.value = ''
    streamingTools.value = {}
    pendingChars.value = []
    pendingFinalMessage.value = null
    currentTurnAssistantMessageReceived.value = false
    currentTurnFallbackErrorShown.value = false
    stopDrain()
    startSecondsTimer()
    currentAbort.value = new AbortController()
    try {
      await aiChatApi.sendMessage(
        session.id,
        { message: msg, attachment_ids: uploadedAttIds, section: opts?.section?.value ?? null, view_context: opts?.viewContext?.value ?? null },
        {
          signal: currentAbort.value.signal,
          onEvent: handleSseEvent,
        },
      )
    } catch (e: any) {
      if (e?.name !== 'AbortError') {
        // 重新抛出，让宿主面板决定如何提示（与 AIChatPage 不同：那里直接弹 ElMessage）
        throw e
      }
    } finally {
      // 等队列清空（让打字动画走完）再切回非流式状态
      let waited = 0
      while (pendingChars.value.length > 0 && waited < 30000) {
        await new Promise(r => setTimeout(r, 50))
        waited += 50
      }
      stopDrain()
      stopSecondsTimer()
      pendingFinalMessage.value = null
      sending.value = false
      currentAbort.value = null
      transientItems.value = []
      streamingText.value = ''
      currentTurnAssistantMessageReceived.value = false
      currentTurnFallbackErrorShown.value = false
      // 重新拉一次 session 拿完整持久化数据（messages + tool_calls + artifacts）
      if (currentSession.value) {
        try { await loadSession(currentSession.value.id) } catch { /* ignore */ }
      }
    }
  }

  async function stop(): Promise<void> {
    const sessionId = currentSession.value?.id ?? null
    if (sessionId) {
      try { await aiChatApi.abort(sessionId) } catch { /* ignore */ }
    }
    currentAbort.value?.abort()
    stopDrain()
    stopSecondsTimer()
    pendingChars.value = []
    pendingFinalMessage.value = null
    sending.value = false
    currentAbort.value = null
    transientItems.value = []
    streamingText.value = ''
    currentTurnAssistantMessageReceived.value = false
    currentTurnFallbackErrorShown.value = false
    if (sessionId) {
      try { await loadSession(sessionId, false) } catch { /* keep current history */ }
    }
  }

  function dispose(): void {
    if (currentAbort.value) {
      try { currentAbort.value.abort() } catch { /* ignore */ }
      currentAbort.value = null
    }
    stopDrain()
    stopSecondsTimer()
  }

  // composable scope 销毁时清理 timers / 进行中的请求
  onScopeDispose(() => {
    dispose()
  })

  return {
    currentSession,
    sessions,
    agentMessages,
    artifacts,
    typing,
    typingSeconds,
    sending,
    currentRunId,
    loadSessions,
    loadSession,
    ensureSession,
    newSession,
    send,
    stop,
    dispose,
  }
}

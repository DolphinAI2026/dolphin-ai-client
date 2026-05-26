// frontend/src/components/v2/config-assistant/composables/useConfigChat.ts
//
// 2026-05-24 拆 ConfigAssistantPanel.vue refactor 产物.
// Config-chat 业务逻辑：messages 状态 / send / SSE 消费 / extractPlan / 计数 modify ops.
//
// 抽出动机: 让 Messages/Input 子组件不直接耦合 API, 主容器把 chat hook 给子组件
// 通过 props/inject. 也方便后续单测 (mock configChatApi).

import { ref, nextTick, type Ref } from 'vue'
import { configChatApi } from '@/api/configChat'
import type { ChatMsg } from '../types'
import type { ConfigChatMessageItem } from '@/api/configChat'

/** 修改类工具集 (Hero CTA 显示条件) — 2026-05-21 Phase 2 */
const MODIFY_TOOL_PATTERN = /^(update_|create_|add_|delete_|disable_|set_)/

export function isModifyTool(toolName: string): boolean {
  return MODIFY_TOOL_PATTERN.test(toolName)
}

export function countModifyOps(msg: ChatMsg): number {
  return (msg.tool_trace || []).filter((t) => t.ok && isModifyTool(t.tool_name)).length
}

/**
 * 从 assistant content 解析"我的计划"块 (顶部独立卡片渲染).
 *
 * 匹配: 开头是"我的计划"/"计划"/"执行计划" + ":" 或 "：" 后跟 markdown list.
 * 返 { planMd, rest } — planMd 渲染 plan card, rest 走普通 bubble.
 * 匹配不到返 { planMd: '', rest: content } 不影响渲染.
 */
export function extractPlan(content: string): { planMd: string; rest: string } {
  if (!content) return { planMd: '', rest: '' }
  const trimmed = content.trimStart()
  const reHeader = /^(?:我的计划|执行计划|计划)\s*[：:]\s*\n+([\s\S]*?)(?:\n{2,}|$)/
  const m = trimmed.match(reHeader)
  if (!m || !m[1]) return { planMd: '', rest: content }
  const planBody = m[1].trim()
  // 必须真是 list (至少 2 行以 数字./-/* 开头)
  const listLines = planBody.split('\n').filter((l) => /^\s*(?:\d+[.、）)]|[-*•])\s+/.test(l))
  if (listLines.length < 2) return { planMd: '', rest: content }
  const rest = content.substring(content.indexOf(m[0]) + m[0].length).trimStart()
  return { planMd: planBody, rest }
}

export function useConfigChat(opts: {
  applicationId: Ref<number>
  scrollerRef: Ref<HTMLElement | null>
  /**
   * 2026-05-24: 模型选择 ref — 由父容器持有 (后续会加 localStorage 持久化)。
   * undefined / null / 0 时, 后端走默认 LLM (跟老行为一致).
   * 子组件 ConfigAssistantHeader 通过 v-model 写回这个 ref.
   */
  modelId?: Ref<number | null>
  /**
   * 2026-05-26 (PR2c SPEC v2 §1.2): SectionNav 当前 section — 软引导.
   * 父 ChatPage 传过来 (跟左侧 SectionNav 同步), 每次 send 时透传给后端.
   * undefined / null → 后端不加 hint (旧行为兼容).
   */
  currentSection?: Ref<string | null>
}) {
  const { applicationId, scrollerRef, modelId, currentSection } = opts

  const messages = ref<ChatMsg[]>([])
  const input = ref('')
  const sending = ref(false)
  /** 2026-05-24 会话持久化：null 表示新对话 (后端首次 send 时自动建 session 并通过 'started' 回 id sticky 到这里) */
  const sessionId = ref<number | null>(null)
  let nextId = 1

  function scrollToBottom() {
    nextTick(() => {
      if (scrollerRef.value) {
        scrollerRef.value.scrollTop = scrollerRef.value.scrollHeight
      }
    })
  }

  async function send() {
    const msg = input.value.trim()
    if (!msg || sending.value) return
    input.value = ''
    sending.value = true

    // Push user message
    messages.value.push({ id: nextId++, role: 'user', content: msg })
    scrollToBottom()

    // Build history for backend (最近 20 条, 去掉刚 push 那条)
    const history = messages.value
      .slice(-20)
      .slice(0, -1)
      .map((m) => ({ role: m.role, content: m.content }))

    // 2026-05-19 image #40: SSE 流式, 实时显示工具调用进度. 先 push 占位 assistant.
    const placeholderId = nextId++
    const placeholder: ChatMsg = {
      id: placeholderId,
      role: 'assistant',
      content: '',
      tool_trace: [],
      streaming: true,
      progressLog: [],
    }
    messages.value.push(placeholder)
    scrollToBottom()

    // 2026-05-24: 把 Header 选的 model_id 透传给后端 (0/null = 后端走默认)
    const requestedModelId = modelId?.value ?? null
    // 2026-05-26 (PR2c): SectionNav 当前 section 透传 — 后端 system_prompt 软引导.
    const requestedSection = currentSection?.value ?? null

    try {
      await configChatApi.chatStream(
        applicationId.value,
        {
          message: msg,
          history,
          model_id: requestedModelId,
          session_id: sessionId.value,
          section: requestedSection,
        },
        (ev: any) => {
          const slot = messages.value.find((m) => m.id === placeholderId) as ChatMsg | undefined
          if (!slot) return

          if (ev.type === 'started') {
            // 2026-05-24: sticky session_id 给后续 send 复用 (新对话时第一轮才有意义)
            if (typeof ev.session_id === 'number' && ev.session_id > 0) {
              sessionId.value = ev.session_id
            }
            slot.progressLog!.push(`📡 connected · ${ev.tools} tools · spec=${ev.spec_source}`)
          } else if (ev.type === 'turn_start') {
            slot.progressLog!.push(`🔄 第 ${ev.turn}/${ev.of} 轮思考`)
          } else if (ev.type === 'tool_call') {
            slot.progressLog!.push(`🔧 ${ev.tool_name}`)
          } else if (ev.type === 'tool_result') {
            slot.tool_trace!.push({
              tool_name: ev.tool_name,
              args: ev.args,
              ok: ev.ok,
              summary: ev.summary,
            })
            slot.progressLog!.push(`${ev.ok ? '✓' : '✗'} ${ev.tool_name}`)
          } else if (ev.type === 'assistant') {
            // 中间轮 (有 tool_calls 时仍有思考文字) 合并显示
            if (ev.content) {
              slot.content = slot.content ? `${slot.content}\n\n${ev.content}` : ev.content
            }
          } else if (ev.type === 'done') {
            slot.content = ev.reply
            slot.change_plan = ev.change_plan
            slot.actions_summary = ev.actions_summary
            slot.tool_trace = ev.tool_trace
            slot.streaming = false
            slot.progressLog = []
            // 2026-05-24: done 也带 session_id, 兜底 sticky (started 偶发漏时)
            if (typeof ev.session_id === 'number' && ev.session_id > 0) {
              sessionId.value = ev.session_id
            }
          } else if (ev.type === 'error') {
            slot.content = `❌ 出错了：${ev.message}`
            slot.streaming = false
            slot.progressLog = []
          }
          scrollToBottom()
        },
      )
    } catch (e: any) {
      const detail = e?.message || '调用失败'
      const slot = messages.value.find((m) => m.id === placeholderId) as ChatMsg | undefined
      if (slot) {
        slot.content = `❌ 网络/解析失败：${detail}`
        slot.streaming = false
        slot.progressLog = []
      }
      scrollToBottom()
    } finally {
      sending.value = false
    }
  }

  function pickExample(text: string) {
    input.value = text
  }

  /**
   * 2026-05-24 会话持久化：清空 messages + sessionId, 用户点 "新对话" 时调.
   * 不调 backend, 下次 send 不带 session_id, 后端自动新建 session.
   */
  function clearMessages() {
    messages.value = []
    sessionId.value = null
    nextId = 1
  }

  /**
   * 2026-05-24 会话持久化：显式设 sessionId. 用户点历史 session 时配合 loadHistory 用.
   * (实际场景下一般直接调 loadHistory, 里面会调 setSession; 暴露独立 setter 给特殊用例.)
   */
  function setSession(sid: number | null) {
    sessionId.value = sid
  }

  /**
   * 2026-05-24 会话持久化：从 server 拉指定 session 的 messages, 替换当前 messages ref.
   * 用户在 SessionDrawer 点某条历史 session 时调.
   *
   * - 清空当前 messages
   * - 拉 server messages → 转 ChatMsg 格式 → push 进 messages
   * - sticky sessionId 到本 session
   * - 失败抛错让 caller 显示 toast
   */
  async function loadHistory(sid: number) {
    if (!sid || sid <= 0) {
      clearMessages()
      return
    }
    const items: ConfigChatMessageItem[] = await configChatApi.getMessages(sid)
    messages.value = []
    nextId = 1
    for (const it of items) {
      const m: ChatMsg = {
        id: nextId++,
        role: it.role,
        content: it.content || '',
      }
      if (it.tool_trace && Array.isArray(it.tool_trace) && it.tool_trace.length) {
        m.tool_trace = it.tool_trace as any
      }
      if (it.change_plan) {
        m.change_plan = it.change_plan
      }
      if (it.actions_summary && Array.isArray(it.actions_summary) && it.actions_summary.length) {
        m.actions_summary = it.actions_summary
      }
      messages.value.push(m)
    }
    sessionId.value = sid
    scrollToBottom()
  }

  return {
    messages,
    input,
    sending,
    send,
    pickExample,
    scrollToBottom,
    // 2026-05-24 会话持久化 exports
    sessionId,
    clearMessages,
    setSession,
    loadHistory,
  }
}

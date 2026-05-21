/**
 * AgentConversation 公共消息类型
 *
 * 4 个 AI 模块（AI Chat / AI 搭建 / 睿鲸 Coding / Vibe Coding）共用此契约渲染对话流。
 * 各模块在自己的 view 里把后端原始消息（StreamMessage / VibeChatMessage / AIChatMessage 等）
 * 映射成 AgentMessage[]，组件侧只认这一套接口。
 */

export type AgentMessageKind =
  | 'user'
  | 'assistant'
  | 'tool'
  | 'thinking'
  | 'ask'
  | 'artifact'
  | 'streaming'
  | 'error'
  | 'status'
  | 'custom'

export interface AgentAttachment {
  id?: string | number
  kind: 'image' | 'file'
  filename: string
  url?: string
  size?: number
}

export interface AgentToolPayload {
  id?: string | number
  name: string                       // 工具名（用于显示 + group key）
  args?: any                         // 入参（任意 JSON）
  argsBrief?: string                 // 一行摘要（如 "src/foo.ts"），优先于 args 显示
  result?: string                    // 结果文本
  /** 工具执行完后的结果摘要（如 "✅ app_id=6 物料管理系统"），父组件按 tool name 解析 result 后填。
   *  ToolCard header 在 duration 之前会显示这段摘要 chip，让用户一眼看出工具到底做成了什么；
   *  父组件不填则 ToolCard 退化为只显 duration（兼容老调用方）。 */
  resultSummary?: string
  status: 'running' | 'success' | 'error' | 'pending'
  duration_ms?: number
  /** 自定义渲染槽 key — 父组件可针对特定工具用 #tool-renderer slot 替换默认卡片 */
  rendererKey?: string
}

export interface AgentAskPayload {
  question: string
  options: string[]
  /** ask 已被回答的选项（用于失活） */
  answered?: string
}

export interface AgentArtifactPayload {
  id?: string | number
  filename: string
  version?: number | string
  preview?: string
  /** 自定义跳转/渲染信息，由父组件拿去用 */
  raw?: any
}

export interface AgentMessage {
  /** 唯一 id（key 用） */
  id: string | number
  kind: AgentMessageKind

  /** kind=user/assistant/streaming/error/status 用：markdown 文本 */
  content?: string
  /** 是否为流式中的消息（光标闪烁） */
  streaming?: boolean

  /** kind=user 用：附件（chips） */
  attachments?: AgentAttachment[]

  /** kind=tool 用 */
  tool?: AgentToolPayload

  /** kind=thinking 用 */
  thinking?: { text: string; locked?: boolean; duration_ms?: number }

  /** kind=ask 用 */
  ask?: AgentAskPayload

  /** kind=artifact 用 */
  artifact?: AgentArtifactPayload

  /** 任意附加 meta，slot 渲染时可拿到 */
  meta?: Record<string, any>
}

/** 同名连续 tool 自动折叠成一组（AIChat 风格） */
export interface AgentToolGroup {
  kind: 'tool_group'
  id: string
  name: string
  tools: AgentToolPayload[]
}

/** 渲染前的 timeline 项 = 单条 AgentMessage 或 一组 tool */
export type AgentTimelineItem = AgentMessage | AgentToolGroup

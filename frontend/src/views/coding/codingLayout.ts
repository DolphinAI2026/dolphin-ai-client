export type CodingMainPaneStyle = {
  flex: string
  width: string
} | null

export function getCodingMainPaneStyle(
  codeFirst: boolean,
  chatExpanded: boolean,
  chatPaneWidth: number,
): CodingMainPaneStyle {
  if (!codeFirst || chatExpanded) return null
  return {
    flex: `0 0 ${chatPaneWidth}px`,
    width: `${chatPaneWidth}px`,
  }
}

export function shouldShowWorkspacePane(
  workspaceId: string | null | undefined,
  embeddedAppId: number | string | null | undefined,
  chatExpanded: boolean,
): boolean {
  return !!workspaceId && !embeddedAppId && !chatExpanded
}

export interface CodingViewState {
  /** 嵌入模式(应用上下文二次开发, ?app_id=) — 走另一套面板, 不动其行为 */
  embedded: boolean
  /** 工作区已打开 */
  codeFirst: boolean
  /** agent 流式生成中 */
  streaming: boolean
  /** 当前会话的消息数 */
  messageCount: number
}

/**
 * 全新 Code 会话的「对话优先欢迎态」: 非嵌入 + 无工作区 + 无消息 + 非流式。
 * 此态渲染欢迎页(说出要开发什么 + 打开本地文件夹/我的开发入口), 而非旧的死板「未选择会话」占位。
 */
export function isCodingWelcome(s: CodingViewState): boolean {
  return !s.embedded && !s.codeFirst && !s.streaming && s.messageCount === 0
}

/**
 * 底部输入框是否显示。
 * - 非嵌入(Code 模式正常使用): 永远显示, 全新会话也能直接输入(修「新建空白没法输入」)。
 * - 嵌入模式: 维持旧行为, 仅当有消息或工作区已开时显示。
 */
export function shouldShowCodingComposer(s: CodingViewState): boolean {
  if (!s.embedded) return true
  return s.messageCount > 0 || s.codeFirst
}

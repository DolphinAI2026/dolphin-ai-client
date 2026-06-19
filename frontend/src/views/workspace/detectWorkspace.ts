// 从对话消息里检测「agent 正在操作的 workspace」。
//
// run_agent 的 workspace 工具(read/write/edit/glob/grep/run_workspace_command)第一个
// 入参都是 ws_id;create_dev_workspace 后续的 write/run 也带同一 ws_id。所以扫工具调用的
// args.ws_id、取最近一个,就是这个会话当前操作的 workspace。
//
// 用途:通用对话里 agent 现场建/改了某 workspace 时,自动把会话绑到它(代码面板点亮 + 显示文件),
// 让「对话 ↔ 代码」连起来。扫的是 agentMessages(含加载的历史)→ 刷新后自愈,无需 URL/后端。

/** 扫描 AgentMessage[](含 kind=tool 单条 与 kind=tool_group 的 tools[]),返回最近一个工具调用
 *  args.ws_id(字符串);无则 null。messages 用 any[] 以兼容 AgentMessage / AgentToolGroup 联合。 */
export function detectWorkspaceId(messages: any[]): string | null {
  if (!Array.isArray(messages)) return null
  let found: string | null = null
  for (const m of messages) {
    const tools =
      m?.kind === 'tool_group' ? (m.tools || []) : m?.kind === 'tool' && m.tool ? [m.tool] : []
    for (const t of tools) {
      const ws = t?.args?.ws_id
      if (typeof ws === 'string' && ws) found = ws // 保留最近(数组顺序在后)
    }
  }
  return found
}

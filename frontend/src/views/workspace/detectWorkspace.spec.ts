import { describe, expect, it } from 'vitest'
import { detectWorkspaceId } from './detectWorkspace'

describe('detectWorkspaceId', () => {
  it('picks ws_id from a kind=tool message args', () => {
    const msgs = [
      { kind: 'user', content: 'hi' },
      { kind: 'tool', tool: { name: 'write_workspace_files', args: { ws_id: '1_88d4df89', files: [] } } },
    ]
    expect(detectWorkspaceId(msgs)).toBe('1_88d4df89')
  })

  it('picks ws_id from a kind=tool_group tools[] args', () => {
    const msgs = [
      { kind: 'tool_group', name: 'edit_workspace_files', tools: [
        { name: 'edit_workspace_files', args: { ws_id: '2_abc', edits: [] } },
        { name: 'edit_workspace_files', args: { ws_id: '2_abc', edits: [] } },
      ] },
    ]
    expect(detectWorkspaceId(msgs)).toBe('2_abc')
  })

  it('returns the LATEST ws_id when multiple workspaces appear', () => {
    const msgs = [
      { kind: 'tool', tool: { name: 'read_workspace_file', args: { ws_id: 'old_1' } } },
      { kind: 'assistant', content: '...' },
      { kind: 'tool', tool: { name: 'run_workspace_command', args: { ws_id: 'new_2', command: 'npm run build' } } },
    ]
    expect(detectWorkspaceId(msgs)).toBe('new_2')
  })

  it('returns null when no tool call carries a ws_id', () => {
    const msgs = [
      { kind: 'user', content: 'hi' },
      { kind: 'tool', tool: { name: 'list_apaas_app_models', args: { app_id: 7 } } },
      { kind: 'assistant', content: 'done' },
    ]
    expect(detectWorkspaceId(msgs)).toBeNull()
  })

  it('is robust to empty / non-array / malformed input', () => {
    expect(detectWorkspaceId([])).toBeNull()
    expect(detectWorkspaceId(undefined as any)).toBeNull()
    expect(detectWorkspaceId([{ kind: 'tool' }, { kind: 'tool_group' }])).toBeNull()
    expect(detectWorkspaceId([{ kind: 'tool', tool: { name: 'x', args: { ws_id: 123 } } }])).toBeNull() // 非字符串 ws_id 忽略
  })
})

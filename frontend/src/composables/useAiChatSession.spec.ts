import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createAiChatSseReducer, useAiChatSession } from './useAiChatSession'
import type { AIChatArtifact, AIChatMessage, AIChatSession, AIChatToolCall } from '@/api/aiChat'

vi.mock('@/api/aiChat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/aiChat')>()
  return {
    ...actual,
    aiChatApi: {
      getSession: vi.fn(),
      listSessions: vi.fn(),
      createSession: vi.fn(),
      updateSession: vi.fn(),
      deleteSession: vi.fn(),
      uploadAttachments: vi.fn(),
      abort: vi.fn(),
      listArtifacts: vi.fn(),
      getArtifact: vi.fn(),
      listArtifactVersions: vi.fn(),
      sendMessage: vi.fn(),
      getRunStatus: vi.fn(),
      attachRun: vi.fn(),
    },
  }
})

const { aiChatApi } = await import('@/api/aiChat')

function makeSession(): AIChatSession {
  return {
    id: 42,
    title: 'Session',
    status: 'active',
    selected_llm_config_id: null,
    workspace_dir: null,
    created_at: null,
    updated_at: null,
  }
}

function makeReducerState() {
  return {
    currentSession: ref<AIChatSession | null>(makeSession()),
    sessions: ref<AIChatSession[]>([]),
    messages: ref<AIChatMessage[]>([]),
    toolCalls: ref<AIChatToolCall[]>([]),
    artifacts: ref<AIChatArtifact[]>([]),
    transientItems: ref<any[]>([]),
    streamingText: ref(''),
    streamingTools: ref<Record<number, any>>({}),
    pendingChars: ref<string[]>([]),
    pendingFinalMessage: ref<AIChatMessage | null>(null),
    currentRunId: ref<string | null>(null),
    currentTurnAssistantMessageReceived: ref(false),
    currentTurnFallbackErrorShown: ref(false),
    ensureDrain: vi.fn(),
    flushPending: vi.fn(),
  }
}

describe('createAiChatSseReducer', () => {
  it('marks assistant_message as received before queueing final message', () => {
    const state = makeReducerState()
    state.pendingChars.value = ['o', 'k']
    const reduce = createAiChatSseReducer(state)
    const message: AIChatMessage = {
      id: 7,
      session_id: 42,
      role: 'assistant',
      content: 'ok',
      created_at: null,
    }

    reduce('assistant_message', message)

    expect(state.currentTurnAssistantMessageReceived.value).toBe(true)
    expect(state.pendingFinalMessage.value).toEqual(message)
    expect(state.messages.value).toEqual([])
  })

  it('adds one local assistant fallback for an SSE error before any assistant message', () => {
    const state = makeReducerState()
    const errors: string[] = []
    const reduce = createAiChatSseReducer({
      ...state,
      onErrorMessage: message => errors.push(message),
    })

    reduce('error', { error: '模型调用失败' })
    reduce('error', { error: '模型调用失败' })

    expect(state.messages.value).toHaveLength(1)
    expect(state.messages.value[0]).toMatchObject({
      session_id: 42,
      role: 'assistant',
      content: '模型调用失败',
      extra_meta: { local_error: true },
    })
    expect(state.currentTurnFallbackErrorShown.value).toBe(true)
    expect(state.transientItems.value).toHaveLength(2)
    expect(errors).toEqual(['模型调用失败', '模型调用失败'])
  })
})

describe('useAiChatSession', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('filters and creates sessions with the requested assistant profile', async () => {
    vi.mocked(aiChatApi.listSessions).mockResolvedValueOnce({ sessions: [] })
    vi.mocked(aiChatApi.createSession).mockResolvedValueOnce({
      ...makeSession(),
      mode: 'code',
      assistant_profile: 'system_assistant',
    })

    const session = useAiChatSession({
      mode: 'code',
      assistantProfile: 'system_assistant',
    })
    await session.loadSessions()
    await session.ensureSession()

    expect(aiChatApi.listSessions).toHaveBeenCalledWith({
      mode: 'code',
      assistant_profile: 'system_assistant',
    })
    expect(aiChatApi.createSession).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'code',
      assistant_profile: 'system_assistant',
    }))
  })

  it('reattaches a running session after loading persisted history', async () => {
    let releaseAttach: (() => void) | undefined
    vi.mocked(aiChatApi.getSession).mockResolvedValueOnce({
      session: makeSession(),
      messages: [],
      attachments: [],
      artifacts: [],
      tool_calls: [],
    })
    vi.mocked(aiChatApi.getRunStatus).mockResolvedValueOnce({
      running: true,
      last_seq: 7,
      run_id: 'run-42',
    })
    vi.mocked(aiChatApi.attachRun).mockImplementationOnce(
      () => new Promise<void>(resolve => { releaseAttach = resolve }),
    )

    const session = useAiChatSession()
    await session.loadSession(42)
    await Promise.resolve()

    expect(aiChatApi.attachRun).toHaveBeenCalledWith(
      42,
      7,
      expect.objectContaining({ onEvent: expect.any(Function) }),
    )
    expect(session.sending.value).toBe(true)
    expect(session.currentRunId.value).toBe('run-42')
    releaseAttach?.()
  })

  it('renders persisted compacted tool arguments without throwing', async () => {
    vi.mocked(aiChatApi.getSession).mockResolvedValueOnce({
      session: makeSession(),
      messages: [],
      attachments: [],
      artifacts: [],
      tool_calls: [
        {
          id: 783,
          session_id: 42,
          message_id: null,
          tool_name: 'run_python',
          args_json: {
            code: {
              _omitted_large_text: true,
              chars: 132,
              preview: "import os\nprint('ok')",
            },
          },
          result_text: '[stdout]\nok',
          status: 'success',
          error_message: null,
          duration_ms: 12,
          started_at: '2026-06-14 09:58:46',
          ended_at: '2026-06-14 09:58:47',
        },
      ],
    })
    vi.mocked(aiChatApi.getRunStatus).mockResolvedValueOnce({ running: false, last_seq: 0, run_id: null })

    const session = useAiChatSession()
    await session.loadSession(42)

    expect(() => session.agentMessages.value).not.toThrow()
    expect(session.agentMessages.value).toMatchObject([
      {
        kind: 'tool',
        tool: {
          name: 'run_python',
          argsBrief: "import os print('ok')…",
        },
      },
    ])
  })

  it('polls a running send every three seconds and clears the stuck working state', async () => {
    vi.useFakeTimers()
    const runningSession = makeSession()
    vi.mocked(aiChatApi.createSession).mockResolvedValueOnce(runningSession)
    vi.mocked(aiChatApi.getRunStatus).mockResolvedValue({ running: false, last_seq: 1, run_id: null })
    vi.mocked(aiChatApi.getSession).mockResolvedValue({
      session: runningSession,
      messages: [{
        id: 101,
        session_id: runningSession.id,
        role: 'user',
        content: 'hello',
        created_at: null,
      }],
      tool_calls: [],
      attachments: [],
      artifacts: [],
    })
    vi.mocked(aiChatApi.sendMessage).mockImplementationOnce((_id, _body, options) => new Promise<void>((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => {
        const error = new Error('aborted')
        error.name = 'AbortError'
        reject(error)
      })
    }))

    const session = useAiChatSession()
    const sendPromise = session.send('hello')
    await vi.advanceTimersByTimeAsync(2999)
    expect(aiChatApi.getRunStatus).not.toHaveBeenCalled()
    expect(session.sending.value).toBe(true)

    await vi.advanceTimersByTimeAsync(1)
    await sendPromise

    expect(aiChatApi.getRunStatus).toHaveBeenCalledWith(runningSession.id)
    expect(session.sending.value).toBe(false)
    expect(session.agentMessages.value).toMatchObject([{ kind: 'user', content: 'hello' }])
  })
})

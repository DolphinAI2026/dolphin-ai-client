import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createAiChatSseReducer } from './useAiChatSession'
import type { AIChatArtifact, AIChatMessage, AIChatSession, AIChatToolCall } from '@/api/aiChat'

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

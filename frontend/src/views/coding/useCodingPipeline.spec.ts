import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const codingStore = vi.hoisted(() => ({
  workspace: { id: 'ws-1' },
  workspacePath: null as string | null,
  conversationId: 1 as number | null,
  setWorkspace: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/stores/coding', () => ({
  useCodingStore: () => codingStore,
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ token: 'test-token' }),
}))

vi.mock('@/api/harness', () => ({
  harnessApi: { codingPipelineUrl: '/api/harness/coding/pipeline' },
}))

vi.mock('@/api/coding', () => ({
  codingApi: {
    listWorkspaces: vi.fn().mockResolvedValue([]),
    getWorkspace: vi.fn().mockResolvedValue({ id: 'ws-1', files: [], status: 'ready' }),
    uploadFile: vi.fn(),
  },
}))

vi.mock('@/utils/sse', () => ({
  consumeSseResponse: async (_response: Response, onEvent: (event: { data: string }) => Promise<void>) => {
    await onEvent({ data: JSON.stringify({ type: 'done', conversation_id: 1, workspace_id: 'ws-1' }) })
  },
}))

describe('useCodingPipeline', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(globalThis as any).window = {}
    ;(globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    })
    codingStore.workspace = { id: 'ws-1' }
    codingStore.conversationId = 1
  })

  it('refreshes conversations after a successful pipeline turn', async () => {
    const { useCodingPipeline } = await import('./useCodingPipeline')
    const streamMessages = ref<any[]>([])
    const refreshCodingConversations = vi.fn().mockResolvedValue(undefined)
    const pipeline = useCodingPipeline({
      model: {
        selectedCodingModelValue: ref(null),
        persistedCodingModelValue: ref(null),
        normalizeCodingModelValue: (v: any) => v,
      },
      stream: {
        streamMessages,
        isStreaming: ref(false),
        addStreamMsg: (msg: any) => streamMessages.value.push(msg),
        appendToLastCommand: vi.fn(),
        appendToLastThinking: vi.fn(),
        completeStepMsg: vi.fn(),
        addStepRunningMsg: vi.fn(),
      },
      workspace: {
        allWorkspaces: ref([]),
      },
      activeSceneCategory: ref('auto'),
      pendingSceneCategory: ref(null),
      sceneCategoryToProjectType: {},
      userInput: ref('读一下代码'),
      attachedFile: ref(null),
      attachedPreviewUrl: ref(null),
      isUploading: ref(false),
      isCreating: ref(false),
      onAfterPipeline: refreshCodingConversations,
    } as any)

    await pipeline.sendMessage()

    expect(refreshCodingConversations).toHaveBeenCalledTimes(1)
  })
})

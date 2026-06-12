import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { codingApi } from '@/api/coding'

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
    ;(globalThis as any).URL.createObjectURL = vi.fn(() => 'blob:preview')
    ;(globalThis as any).URL.revokeObjectURL = vi.fn()
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

  it('keeps uploaded images visible in the user turn and passes attachment metadata to backend', async () => {
    const { useCodingPipeline } = await import('./useCodingPipeline')
    const streamMessages = ref<any[]>([])
    const file = { name: 'dict.png', type: 'image/png' } as File
    ;(codingApi.uploadFile as any).mockResolvedValue({
      filename: 'dict.png',
      content_type: 'image/png',
      file_path: '/tmp/ws/uploads/abc_dict.png',
      relative_path: 'uploads/abc_dict.png',
      preview_url: '/api/coding/workspace/ws-1/raw?file_path=uploads%2Fabc_dict.png',
    })
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
      userInput: ref('数据字典是不是没有生成全啊?'),
      attachedFile: ref(file),
      attachedPreviewUrl: ref('blob:preview'),
      isUploading: ref(false),
      isCreating: ref(false),
    } as any)

    await pipeline.sendMessage()

    const userMsg = streamMessages.value.find(m => m.type === 'user')
    expect(userMsg?.content).toBe('数据字典是不是没有生成全啊?')
    expect(userMsg?.attachments).toEqual([{
      kind: 'image',
      filename: 'dict.png',
      url: '/api/coding/workspace/ws-1/raw?file_path=uploads%2Fabc_dict.png',
    }])

    const fetchBody = JSON.parse((globalThis.fetch as any).mock.calls[0][1].body)
    expect(fetchBody.attachments).toEqual([{
      kind: 'image',
      filename: 'dict.png',
      url: '/api/coding/workspace/ws-1/raw?file_path=uploads%2Fabc_dict.png',
      relative_path: 'uploads/abc_dict.png',
      content_type: 'image/png',
    }])
  })
})

/**
 * useCodingPipeline — 智能开发 SSE 流水线编排。
 *
 * 职责：
 * - SSE 事件 dispatch map（step / content / agent_tool / done / ... 共 12 种）
 * - STEP_HANDLERS / TOOL_HANDLERS 子查表
 * - 附件上传 / pipeline 请求构造 / SSE 消费 / IDE URL 兜底
 * - sendMessage 编排：上传 → 构建请求 → fetch → 消费 SSE → 后置 IDE 加载
 *
 * 依赖前面 4 个 composable 的返回值 + 几个组件级 ref，通过 deps 参数显式传入。
 */

import type { Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'

import { useCodingStore } from '@/stores/coding'
import { useUserStore } from '@/stores/user'
import { consumeSseResponse } from '@/utils/sse'
import { codingApi } from '@/api/coding'
import { harnessApi } from '@/api/harness'

import { formatSceneType } from './useStreamMessages'
import type { useCodingModel } from './useCodingModel'
import type { useStreamMessages } from './useStreamMessages'
import type { useIdeManager } from './useIdeManager'
import type { useCodingWorkspace } from './useCodingWorkspace'

type ModelDeps = ReturnType<typeof useCodingModel>
type StreamDeps = ReturnType<typeof useStreamMessages>
type IdeDeps = ReturnType<typeof useIdeManager>
type WorkspaceDeps = ReturnType<typeof useCodingWorkspace>

export interface PipelineDeps {
  model: ModelDeps
  stream: StreamDeps
  ide: IdeDeps
  workspace: WorkspaceDeps
  /** 组件级场景选择 ref（仅用于建议示例分组展示；实际场景由 LLM 从 message 识别） */
  activeSceneCategory: Ref<string>
  pendingSceneCategory: Ref<string | null>
  /** 组件级输入 / 上传 ref */
  userInput: Ref<string>
  attachedFile: Ref<File | null>
  attachedPreviewUrl: Ref<string | null>
  isUploading: Ref<boolean>
  isCreating: Ref<boolean>
}

export function useCodingPipeline(deps: PipelineDeps) {
  const codingStore = useCodingStore()
  const userStore = useUserStore()
  const route = useRoute()

  const {
    model: {
      selectedCodingModelValue,
      persistedCodingModelValue,
      normalizeCodingModelValue,
    },
    stream: {
      streamMessages,
      isStreaming,
      addStreamMsg,
      appendToLastCommand,
      appendToLastThinking,
      completeStepMsg,
      addStepRunningMsg,
    },
    ide: {
      ideUrl,
      pendingIdeUrl,
      setIdeUrl,
      activeView,
    },
    workspace: { allWorkspaces, embeddedAppId },
    activeSceneCategory,
    pendingSceneCategory,
    userInput,
    attachedFile,
    attachedPreviewUrl,
    isUploading,
    isCreating,
  } = deps

  // ── STEP / TOOL 子查表 ──

  const STEP_HANDLERS: Record<string, { running?: string; done: string; onDone?: (data: any) => void | Promise<void> }> = {
    detect_scene: {
      done: '',  // label 动态生成
      onDone: (data) => {
        const label = formatSceneType(data?.scene_type || 'component')
        completeStepMsg('detect_scene', `识别为 ${label}`)
      },
    },
    create_workspace: {
      running: '正在初始化工程脚手架...',
      done: '工程脚手架已初始化',
      onDone: async (data) => {
        if (!data) return
        const wsData = { ...data, id: data.workspace_id || data.id }
        codingStore.setWorkspace(wsData)
        codingStore.workspacePath = data.workspace_path || null
        localStorage.setItem('coding_last_workspace_id', wsData.id)
        try { allWorkspaces.value = await codingApi.listWorkspaces() } catch {}
      },
    },
    brainstorm: { running: '正在生成需求确认...', done: '需求确认已生成' },
    generate: { running: 'AI 开始编写代码...', done: '代码生成完成' },
  }

  const TOOL_HANDLERS: Record<string, (args: any, preview: string) => void> = {
    write_file: (args, preview) => {
      const fileName = ((args.file_path || '') as string).split('/').pop() || preview
      addStreamMsg({ type: 'file_write', content: '', fileName, fileContent: args.content || undefined, collapsed: true })
    },
    edit_file: (args, preview) => {
      const fileName = ((args.file_path || '') as string).split('/').pop() || preview
      addStreamMsg({ type: 'file_edit', content: '', fileName, fileContent: args.new_string || undefined, collapsed: true })
    },
    run_command: (args, preview) => addStreamMsg({ type: 'command', content: (args.command || preview || '') as string }),
    read_file: (_args, preview) => addStreamMsg({ type: 'tool', content: `\uD83D\uDCC4 \u8BFB\u53D6 ${preview}` }),
    glob_files: (_args, preview) => addStreamMsg({ type: 'tool', content: `\uD83D\uDCC2 \u626B\u63CF ${preview || '\u9879\u76EE\u6587\u4EF6'}` }),
    grep_search: (_args, preview) => addStreamMsg({ type: 'tool', content: `\uD83D\uDD0D \u641C\u7D22 ${preview}` }),
  }

  /** 播放代码生成完成的提示音（E6 正弦波 350ms）。浏览器自动播放策略失败时静默跳过。 */
  function playDoneChime() {
    try {
      const ctx = new AudioContext()
      const gain = ctx.createGain()
      gain.connect(ctx.destination)
      gain.gain.setValueAtTime(0, ctx.currentTime)
      gain.gain.linearRampToValueAtTime(0.08, ctx.currentTime + 0.005)
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35)
      const osc = ctx.createOscillator()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(1318, ctx.currentTime) // E6
      osc.connect(gain)
      osc.start(ctx.currentTime)
      osc.stop(ctx.currentTime + 0.35)
      osc.onended = () => ctx.close()
    } catch (_) {}
  }

  // ── SSE 事件 dispatch map ──

  const sseHandlers: Record<string, (parsed: any) => void | Promise<void>> = {
    step: async (parsed) => {
      const cfg = STEP_HANDLERS[parsed.step as string]
      if (!cfg) return
      if (parsed.status === 'running' && cfg.running) {
        addStepRunningMsg(cfg.running, parsed.step)
      } else if (parsed.status === 'done') {
        if (cfg.done) completeStepMsg(parsed.step, cfg.done)
        if (cfg.onDone) await cfg.onDone(parsed.data)
      }
    },
    content: (parsed) => {
      const text = (parsed.content || '') as string
      if (text.trim()) addStreamMsg({ type: 'message', content: text })
    },
    agent_tool: (parsed) => {
      const handler = TOOL_HANDLERS[parsed.tool as string]
      if (handler) handler(parsed.args || {}, (parsed.input_preview || '') as string)
    },
    agent_command_output: (parsed) => {
      const chunk = (parsed.chunk || '') as string
      if (chunk) appendToLastCommand(chunk)
    },
    agent_result: (parsed) => {
      const preview = (parsed.output_preview || '') as string
      if (parsed.is_error) {
        addStreamMsg({ type: 'error', content: preview || '执行失败' })
      } else if (preview) {
        // 将结果挂到上一条 tool 消息，使其变为可折叠卡片
        const last = streamMessages.value[streamMessages.value.length - 1]
        if (last?.type === 'tool') {
          last.result = preview
          last.resultCollapsed = true
        }
      }
    },
    agent_thinking: (parsed) => {
      // 后端每轮 LLM 思考会 emit 两次：逐 token 的 agent_thinking_delta（流式）
      // + 末尾一次完整的 agent_thinking（全文）。delta 流通常已经把完整内容
      // 累积到 streamMessages 最后一条 thinking 卡片上了，这里的 agent_thinking
      // 事件只做两件事：
      //   1) 如果 delta 流丢失几段，用完整 text 补齐最后这条 thinking 卡片
      //   2) 如果 delta 流完全没出现过（最后一条不是 thinking），fallback 新建
      // 之前的 last.content.includes(text.slice(0, 50)) 判断在短文本/delta 不全
      // 的情况下会误判，导致同卡片里文字重复两遍。
      const text = (parsed.content || '') as string
      if (!text.trim()) return
      const last = streamMessages.value[streamMessages.value.length - 1]
      if (last?.type === 'thinking') {
        // delta 已经在累积；text 是完整全文，用长度兜底补齐（delta 短则覆盖）
        if (last.content.length < text.length) {
          last.content = text
        }
        return
      }
      // delta 流没创建 thinking 卡片（罕见），fallback 新建
      addStreamMsg({ type: 'thinking', content: text })
    },
    agent_thinking_delta: (parsed) => {
      const delta = (parsed.content || '') as string
      if (delta) appendToLastThinking(delta)
    },
    serve_started: (parsed) => {
      const url = (parsed.url || '') as string
      if (!url) return
      try { (window as any).__apaasDebug?.addRecord(url) } catch (_) {}
      addStreamMsg({ type: 'message', content: `调试服务已启动：${url}` })
    },
    agent_done: () => {
      addStreamMsg({ type: 'status', content: '\u2705 \u4EE3\u7801\u751F\u6210\u5B8C\u6210' })
    },
    scene_detected: (parsed) => {
      codingStore.conversationId = parsed.conversation_id
    },
    done: async (parsed) => {
      isStreaming.value = false
      isCreating.value = false  // 立即解除输入框禁用，后续 API 在后台继续
      codingStore.conversationId = parsed.conversation_id
      if (parsed.conversation_id) {
        persistedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
      }
      if (parsed.workspace_id && !codingStore.workspace) {
        try {
          const ws = await codingApi.getWorkspace(parsed.workspace_id)
          codingStore.setWorkspace(ws)
          localStorage.setItem('coding_last_workspace_id', ws.id)
        } catch { /* ignore */ }
      }
      if (parsed.ide_url && !parsed.waiting_confirmation) {
        pendingIdeUrl.value = parsed.ide_url
        if (!ideUrl.value) setIdeUrl(parsed.ide_url)
      }
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('aPaaS Builder', {
          body: parsed.waiting_confirmation ? '设计方案已生成，请确认后开始生成代码' : '代码已生成完成，快来看看吧',
        })
      }
      playDoneChime()
    },
    error: (parsed) => {
      addStreamMsg({ type: 'error', content: parsed.message || '\u53D1\u751F\u9519\u8BEF' })
      isStreaming.value = false
    },
  }

  // ── 辅助函数（上传 / 构建请求 / 消费 SSE / 后置 IDE 加载）──

  async function consumePipelineSse(response: Response): Promise<void> {
    let sseParseErrors = 0
    await consumeSseResponse(response, async ({ data }) => {
      const payload = data.trim()
      if (!payload || payload === '[DONE]') return
      try {
        const parsed = JSON.parse(payload)
        const handler = sseHandlers[parsed.type as string]
        if (handler) await handler(parsed)
      } catch (parseErr) {
        sseParseErrors++
        if (sseParseErrors <= 3) {
          console.warn(`[CodingPage] SSE parse error #${sseParseErrors}:`, parseErr)
        }
        if (sseParseErrors === 5) {
          ElMessage.warning('部分 SSE 事件解析失败，结果可能不完整')
        }
      }
    }, { yieldEvery: 6 })
  }

  async function loadIdeUrlAfterPipeline(): Promise<void> {
    if (!ideUrl.value && codingStore.workspace) {
      try {
        const { ide_url } = await codingApi.getIdeUrl(codingStore.workspace.id, codingStore.conversationId)
        pendingIdeUrl.value = ide_url
        await setIdeUrl(ide_url)
      } catch (err: any) {
        ElMessage.warning(err?.message || 'IDE URL 获取失败')
      }
    }
    if (codingStore.workspace) {
      try { allWorkspaces.value = await codingApi.listWorkspaces() } catch {}
    }
  }

  function buildPipelineRequest(finalMessage: string, _sceneKey: string): Record<string, any> {
    return {
      message: finalMessage,
      workspace_id: codingStore.workspace?.id || null,
      conversation_id: codingStore.conversationId || null,
      selected_model: selectedCodingModelValue.value || null,
      app_id: (route.query.app_id as string) || null,
      project_id: embeddedAppId.value ? Number(embeddedAppId.value) : null,
    }
  }

  async function uploadAttachmentIfPresent(
    message: string,
    file: File | null,
    previewUrl: string | null,
  ): Promise<string> {
    if (!file) return message

    let uploadResult: any = null
    try {
      isUploading.value = true
      uploadResult = await codingApi.uploadFile(file, codingStore.workspace?.id)
    } catch (e: any) {
      ElMessage.error(`\u9644\u4EF6\u4E0A\u4F20\u5931\u8D25: ${e.message}`)
    } finally {
      isUploading.value = false
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }

    if (!uploadResult) return message
    if (uploadResult.content) {
      return `[\u9644\u4EF6\u6587\u6863: ${uploadResult.filename}]\n\`\`\`\n${uploadResult.content}\n\`\`\`\n\n${message}`
    }
    return `${message}\n\n[\u9644\u4EF6\u56FE\u7247: ${uploadResult.filename}, \u5DF2\u4FDD\u5B58\u81F3: ${uploadResult.file_path}]`
  }

  // ── 主流程 ──

  async function sendMessage() {
    const message = userInput.value.trim()
    if (!message && !attachedFile.value) return
    if (isCreating.value) return

    userInput.value = ''
    const currentAttachment = attachedFile.value
    const currentPreviewUrl = attachedPreviewUrl.value
    attachedFile.value = null
    attachedPreviewUrl.value = null

    isCreating.value = true
    isStreaming.value = true
    activeView.value = 'chat'
    // 保留历史消息，多轮之间加分隔
    if (streamMessages.value.length > 0) {
      addStreamMsg({ type: 'status', content: '───' })
    }
    addStreamMsg({ type: 'user', content: message })
    addStreamMsg({ type: 'status', content: codingStore.workspace ? '正在处理...' : '正在识别开发场景...', stepKey: codingStore.workspace ? undefined : 'detect_scene' })

    try {
      const finalMessage = await uploadAttachmentIfPresent(message, currentAttachment, currentPreviewUrl)

      const sceneKey = pendingSceneCategory.value || activeSceneCategory.value
      pendingSceneCategory.value = null
      const body = buildPipelineRequest(finalMessage, sceneKey)

      const response = await fetch(harnessApi.codingPipelineUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${userStore.token}`,
        },
        body: JSON.stringify(body),
      })

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
        throw new Error(errBody.detail || `HTTP ${response.status}`)
      }

      await consumePipelineSse(response)
      await loadIdeUrlAfterPipeline()

    } catch (error: any) {
      addStreamMsg({ type: 'error', content: error.message || '\u53D1\u751F\u9519\u8BEF' })
      isStreaming.value = false
    } finally {
      isCreating.value = false
    }
  }

  function sendSuggestion(text: string) {
    userInput.value = text
    pendingSceneCategory.value = activeSceneCategory.value
    sendMessage()
  }

  return {
    sendMessage,
    sendSuggestion,
    // 暴露给 replay / 其他地方用（很少直接用）
    consumePipelineSse,
    loadIdeUrlAfterPipeline,
  }
}

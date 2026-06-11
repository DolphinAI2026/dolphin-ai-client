/**
 * useCodingPipeline — 智能开发 SSE 流水线编排。
 *
 * 职责：
 * - SSE 事件 dispatch map（step / content / agent_tool / done / ... 共 12 种）
 * - STEP_HANDLERS / TOOL_HANDLERS 子查表
 * - 附件上传 / pipeline 请求构造 / SSE 消费
 * - sendMessage 编排：上传 → 构建请求 → fetch → 消费 SSE
 *
 * 依赖前面 3 个 composable 的返回值 + 几个组件级 ref，通过 deps 参数显式传入。
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
import type { useCodingWorkspace } from './useCodingWorkspace'

type ModelDeps = ReturnType<typeof useCodingModel>
type StreamDeps = ReturnType<typeof useStreamMessages>
type WorkspaceDeps = ReturnType<typeof useCodingWorkspace>

export interface PipelineDeps {
  model: ModelDeps
  stream: StreamDeps
  workspace: WorkspaceDeps
  /** 组件级场景选择 ref（首次消息用） */
  activeSceneCategory: Ref<string>
  pendingSceneCategory: Ref<string | null>
  sceneCategoryToProjectType: Record<string, string>
  /** 组件级输入 / 上传 ref */
  userInput: Ref<string>
  attachedFile: Ref<File | null>
  attachedPreviewUrl: Ref<string | null>
  isUploading: Ref<boolean>
  isCreating: Ref<boolean>
  /** 分场景入口「在应用上定制」选中的目标应用 id —— 绑定给 codegen（首条消息带 app_id）。
   *  不走 route.query.app_id：那个会触发 embeddedAppId 进嵌入式布局。 */
  boundAppId?: Ref<number | null>
  /** pipeline 结束后刷新会话元信息（workspace_id / updated_at / title 等）。 */
  onAfterPipeline?: () => void | Promise<void>
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
    workspace: { allWorkspaces },
    activeSceneCategory,
    pendingSceneCategory,
    sceneCategoryToProjectType,
    userInput,
    attachedFile,
    attachedPreviewUrl,
    isUploading,
    isCreating,
    boundAppId,
    onAfterPipeline,
  } = deps

  function resolveRouteProjectId(): number | null {
    const raw = route.query.project_id
    const projectId = Number(Array.isArray(raw) ? raw[0] : raw)
    return Number.isFinite(projectId) && projectId > 0 ? projectId : null
  }

  // ── STEP / TOOL 子查表 ──

  const STEP_HANDLERS: Record<string, { running?: string; done: string; onDone?: (data: any) => void | Promise<void> }> = {
    detect_scene: {
      done: '',  // label 动态生成
      onDone: (data) => {
        const label = formatSceneType(data?.scene_type || 'component')
        completeStepMsg('detect_scene', `识别为 ${label}`)
      },
    },
    read_app_context: {
      running: '正在读取应用上下文…',
      done: '已读取应用上下文',
      onDone: (data) => {
        completeStepMsg('read_app_context', data?.label || '已读取应用上下文')
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
    brainstorm: {
      running: '正在生成开发 SPEC...',
      done: '',  // label 据后端 data.outcome 动态生成(clarify/spec/skip)
      onDone: (data) => {
        // 澄清轮不该贴「开发 SPEC 待确认」—— 那轮没出 SPEC,是抛了澄清问题等回答。
        const outcome = data?.outcome
        const label = outcome === 'clarify'
          ? '澄清问题待回答'
          : outcome === 'skip'
            ? '已分析需求'
            : '开发 SPEC 待确认'
        completeStepMsg('brainstorm', label)
      },
    },
    generate: { running: 'AI 开始编写代码...', done: '代码生成完成' },
  }

  /** 工具 args 里的 file_path 可能带工作区绝对前缀，归一成工作区相对路径（文件卡点击直达查看器用） */
  function toWsRelativePath(p: string): string {
    let s = (p || '').replace(/\\/g, '/').trim()
    const ws = (codingStore.workspacePath || '').replace(/\\/g, '/').replace(/\/+$/, '')
    if (ws && s.startsWith(ws + '/')) s = s.slice(ws.length + 1)
    return s.replace(/^\.?\//, '')
  }

  const TOOL_HANDLERS: Record<string, (args: any, preview: string) => void> = {
    write_file: (args, preview) => {
      const filePath = toWsRelativePath((args.file_path || '') as string)
      const fileName = filePath.split('/').pop() || preview
      addStreamMsg({ type: 'file_write', content: '', fileName, filePath: filePath || undefined, fileContent: args.content || undefined, collapsed: true })
    },
    edit_file: (args, preview) => {
      const filePath = toWsRelativePath((args.file_path || '') as string)
      const fileName = filePath.split('/').pop() || preview
      // old + new 都带上,FileCard 渲染红绿 diff(对齐 Claude Code)
      addStreamMsg({
        type: 'file_edit', content: '', fileName, filePath: filePath || undefined,
        fileContent: (args.new_string ?? args.content) || undefined,
        oldContent: args.old_string || undefined,
        collapsed: true,
      })
    },
    run_command: (args, preview) => addStreamMsg({ type: 'command', content: (args.command || preview || '') as string }),
    read_file: (_args, preview) => addStreamMsg({ type: 'tool', content: `📄 读取 ${preview}` }),
    glob_files: (_args, preview) => addStreamMsg({ type: 'tool', content: `📂 扫描 ${preview || '项目文件'}` }),
    grep_search: (_args, preview) => addStreamMsg({ type: 'tool', content: `🔍 搜索 ${preview}` }),
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
      // READ 路径流式增量: 追加到最后一条增量 message(打字机), 中间隔了工具卡就开新气泡
      if (parsed.delta) {
        if (!text) return
        const last = streamMessages.value[streamMessages.value.length - 1]
        if (last?.type === 'message' && last.deltaStream) {
          last.content += text
        } else {
          addStreamMsg({ type: 'message', content: text, deltaStream: true })
        }
        return
      }
      if (text.trim()) addStreamMsg({ type: 'message', content: text })
    },
    // 澄清门:结构化问题 + 可点选项(对齐 Builder),渲染成 ask 卡片
    clarify: (parsed) => {
      addStreamMsg({
        type: 'clarify',
        content: (parsed.question || '') as string,
        question: (parsed.question || '') as string,
        options: Array.isArray(parsed.options) ? parsed.options : [],
      })
    },
    // N1 READ 路径:只读工具事件 → 工具卡 + 把"正在识别开发场景"占位换成"已理解为查询请求"
    tool: (parsed) => {
      const ph = streamMessages.value.find(
        (m: any) => m.type === 'status' && m.stepKey === 'detect_scene' && !m.stepDone,
      ) as any
      if (ph) { ph.content = '已理解为查询请求'; ph.stepDone = true }
      if (parsed.status === 'done') {
        for (let i = streamMessages.value.length - 1; i >= 0; i--) {
          const m = streamMessages.value[i] as any
          if (m.type === 'tool') {
            m.result = (parsed.result || '') as string
            m.resultCollapsed = true
            break
          }
        }
      } else {
        addStreamMsg({ type: 'tool', content: `🔧 ${parsed.display || parsed.name || '查询'}`, resultCollapsed: true } as any)
      }
    },
    agent_tool: (parsed) => {
      const handler = TOOL_HANDLERS[parsed.tool as string]
      // 后端 write_file/edit_file 把内容放在 parsed.input(不是 args);兼容旧字段。
      if (handler) {
        handler(parsed.input || parsed.args || {}, (parsed.input_preview || '') as string)
      } else if (parsed.tool && parsed.tool !== 'ask_clarifying_question') {
        // 未注册的工具(只读路径的 读取文件/搜索代码、agent 的 aPaaS 读工具等)
        // 渲染通用 chip,别静默丢——agent_result 会把结果挂上来变成可折叠卡片。
        addStreamMsg({ type: 'tool', content: `🔧 ${parsed.tool_display || parsed.tool}`, toolName: parsed.tool, resultCollapsed: true })
      }
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
        // 结果回填: 同轮工具并行执行后 done 批量到达, "挂到最后一条"会全堆在末尾
        // chip 上 → 先按工具名正向找第一个未回填的 chip, 找不到再退回旧的"最后一条"。
        const list = streamMessages.value
        let target = null as (typeof list)[number] | null
        if (parsed.tool) {
          target = list.find(m => m.type === 'tool' && m.toolName === parsed.tool && !m.result) || null
        }
        if (!target) {
          const last = list[list.length - 1]
          if (last?.type === 'tool' && !last.result) target = last
        }
        if (target) {
          target.result = preview
          target.resultCollapsed = true
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
      addStreamMsg({ type: 'status', content: '✅ 代码生成完成' })
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
      if ('Notification' in window && Notification.permission === 'granted') {
        const _notifyBody = parsed.waiting_clarification
          ? '有几个问题想先和你对齐一下，回答后继续'
          : (parsed.waiting_confirmation ? '开发 SPEC 已生成，请确认后开始生成代码' : '代码已生成完成，快来看看吧')
        new Notification('aPaaS Builder', { body: _notifyBody })
      }
      playDoneChime()
    },
    error: (parsed) => {
      addStreamMsg({ type: 'error', content: parsed.message || '发生错误' })
      isStreaming.value = false
    },
  }

  // ── 辅助函数（上传 / 构建请求 / 消费 SSE）──

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

  async function refreshWorkspacesAfterPipeline(): Promise<void> {
    if (codingStore.workspace) {
      try { allWorkspaces.value = await codingApi.listWorkspaces() } catch {}
    }
  }

  function buildPipelineRequest(finalMessage: string, sceneKey: string): Record<string, any> {
    return {
      message: finalMessage,
      workspace_id: codingStore.workspace?.id || null,
      conversation_id: codingStore.conversationId || null,
      selected_model: selectedCodingModelValue.value || null,
      // 分场景入口选中的目标应用优先（codegen 据此复用 app 的模型/接口/枚举）；
      // 回退 route.query.app_id（Builder handoff / 嵌入式）。
      app_id: boundAppId?.value != null ? String(boundAppId.value) : ((route.query.app_id as string) || null),
      project_id: resolveRouteProjectId(),
      project_type: sceneCategoryToProjectType[sceneKey] || (route.query.type as string) || null,
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
      ElMessage.error(`附件上传失败: ${e.message}`)
    } finally {
      isUploading.value = false
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }

    if (!uploadResult) return message
    if (uploadResult.content) {
      return `[附件文档: ${uploadResult.filename}]\n\`\`\`\n${uploadResult.content}\n\`\`\`\n\n${message}`
    }
    return `${message}\n\n[附件图片: ${uploadResult.filename}, 已保存至: ${uploadResult.file_path}]`
  }

  // ── 主流程 ──

  // 当前流式请求的中止器:用户点「停止」→ abort() → fetch/SSE 抛 AbortError → 收尾(不弹错)。
  let currentAbort: AbortController | null = null
  function stopStream() {
    if (currentAbort) currentAbort.abort()
    isStreaming.value = false  // 立即翻转,UI 不等 abort 落地;后续事件不会再把它设回 true
  }

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
    // 保留历史消息，多轮之间加分隔
    if (streamMessages.value.length > 0) {
      addStreamMsg({ type: 'status', content: '───' })
    }
    addStreamMsg({ type: 'user', content: message })
    // 首条占位用中性文案：此时还没分类 read/build,不能预设"识别开发场景"(那是 codegen 话术,
    // READ 问答会显得不对)。READ → tool 事件把它换成"已理解为查询请求";BUILD → detect_scene 完成换成"识别为 X"。
    addStreamMsg({ type: 'status', content: codingStore.workspace ? '正在处理...' : '正在理解你的需求...', stepKey: codingStore.workspace ? undefined : 'detect_scene' })

    try {
      const finalMessage = await uploadAttachmentIfPresent(message, currentAttachment, currentPreviewUrl)

      const sceneKey = pendingSceneCategory.value || activeSceneCategory.value
      pendingSceneCategory.value = null
      const body = buildPipelineRequest(finalMessage, sceneKey)

      currentAbort = new AbortController()
      const response = await fetch(harnessApi.codingPipelineUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${userStore.token}`,
        },
        body: JSON.stringify(body),
        signal: currentAbort.signal,
      })

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
        throw new Error(errBody.detail || `HTTP ${response.status}`)
      }

      await consumePipelineSse(response)
      await refreshWorkspacesAfterPipeline()
      await onAfterPipeline?.()

    } catch (error: any) {
      // 用户主动「停止」→ AbortError:静默收尾,不弹错、补一条提示。
      if (error?.name === 'AbortError') {
        addStreamMsg({ type: 'status', content: '已停止生成' })
      } else {
        addStreamMsg({ type: 'error', content: error.message || '发生错误' })
      }
      isStreaming.value = false
    } finally {
      isCreating.value = false
      currentAbort = null
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
    stopStream,
    // 暴露给 replay / 其他地方用（很少直接用）
    consumePipelineSse,
    refreshWorkspacesAfterPipeline,
  }
}

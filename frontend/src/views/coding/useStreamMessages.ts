/**
 * useStreamMessages — 智能开发对话流消息相关状态和行为。
 *
 * 职责：
 * - `streamMessages` 列表的添加 / 追加 / 场景 badge 转换
 * - 自动滚动到容器底部
 * - replay 历史消息时把进行中状态还原为 badge
 * - 场景类型 value → 中文 label 映射（formatSceneType）
 */

import { ref, nextTick } from 'vue'
import { marked } from 'marked'

import type { CodingAttachment, ReplayStreamMessage } from '@/api/coding'

export interface StreamMessage {
  type: 'user' | 'thinking' | 'tool' | 'file_write' | 'file_edit' | 'command' | 'status' | 'error' | 'message' | 'clarify'
  content: string
  fileName?: string
  /** 工作区相对全路径(嵌套文件 basename 对不上树), 点击文件卡直达查看器用 */
  filePath?: string
  fileContent?: string
  /** type=file_edit 用:修改前内容,FileCard 据 old→new 渲染红绿 diff */
  oldContent?: string
  collapsed?: boolean
  result?: string
  resultCollapsed?: boolean
  /** type=message 用: READ 路径流式增量正在追加中 */
  deltaStream?: boolean
  /** type=tool 用: 工具名(并行执行时结果按名回填, 不再"挂到最后一条") */
  toolName?: string
  /** type=clarify 用:澄清问题 + 可点选项(对齐 Builder 的 ask_clarifying_question) */
  question?: string
  options?: string[]
  /** 用户已选/答的选项(选后置灰) */
  answered?: string
  /** pipeline step 归属，用于原地更新 */
  stepKey?: string
  /** true = 显示为完成 badge 芯片 */
  stepDone?: boolean
  /** true = 隐藏（被后续完成消息替代） */
  hidden?: boolean
  /** 用户消息附件，用于保留截图/文件可见性 */
  attachments?: CodingAttachment[]
  timestamp: number
}

const SCENE_TYPE_LABEL: Record<string, string> = {
  web_component: 'PC 端自开发组件',
  web_component_dual: '双端自开发组件',
  form_component: 'PC 端自开发组件',
  component: '自开发组件',
  mobile_component: '双端自开发组件',
  web_page: '自开发页面',
  web_list_view: '自开发列表视图',
  web_layout: '自定义布局',
  web_login: '自定义登录页',
  web_plugin: '自开发插件',
  mobile_page: '移动端页面',
  page: '自开发页面',
  backend_api: '后端接口',
  backend_feign: '外部接口调用',
  backend_scheduled: '后端定时任务',
  api: '后端接口',
  backend: '后端接口',
  service: '后端服务',
  script_js: 'JS 脚本扩展',
  script_python: 'Python 脚本扩展',
  script_groovy: 'Groovy 脚本扩展',
  business_dialog: '业务事件弹窗',
  ui_style: '界面样式扩展',
  list_custom_module: '列表自定义模块',
}

export function formatSceneType(raw: string): string {
  return SCENE_TYPE_LABEL[raw] || raw
}

export function renderMarkdown(content: string): string {
  if (!content) return ''
  try {
    return marked.parse(content) as string
  } catch {
    return content
  }
}

/** 清理模型输出中的 think 标签和多余空行 */
function cleanThinkTags(text: string): string {
  return text
    .replace(/<\/?think>/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

// ── replay 历史消息识别模式 ──
const STEP_RUNNING_PATTERNS = [
  '正在理解你的需求',
  '正在识别开发场景',
  '正在生成开发 SPEC',
  '正在初始化工程脚手架',
  'AI 开始编写代码',
  '正在处理',
]
const STEP_DONE_PATTERNS: [RegExp, string | null][] = [
  [/^✓\s*识别为\s+(.+)$/, null],          // 保留原文，转 badge
  [/^✓\s*开发 SPEC 待确认$/, '开发 SPEC 待确认'],
  [/^✓\s*工程脚手架已初始化$/, '工程脚手架已初始化'],
  [/^✓\s*代码生成完成$/, '代码生成完成'],
  [/^✅\s*代码生成完成$/, '代码生成完成'],
]
/** 工具执行结果 pattern — 在旧数据中以 status 消息保存，现在应跳过（文件卡片已表达同等信息） */
const TOOL_RESULT_PATTERNS = [
  /^✅\s+Successfully\s/i,
  /^Successfully\s+(wrote|read|ran|created|deleted|moved)\s/i,
]

function replayIsRunning(content: string) {
  return STEP_RUNNING_PATTERNS.some(p => content.includes(p))
}

function isToolResultMsg(content: string) {
  return TOOL_RESULT_PATTERNS.some(p => p.test(content))
}

function replayAsBadge(content: string): string | null {
  for (const [re, label] of STEP_DONE_PATTERNS) {
    const m = content.match(re)
    if (m) {
      if (label) return label
      // 动态内容：取匹配组 1（如"识别为 自开发组件"中的 sceneType）
      const raw = m[1]?.trim() || ''
      return `识别为 ${formatSceneType(raw)}`
    }
  }
  return null
}

export function useStreamMessages() {
  const streamMessages = ref<StreamMessage[]>([])
  const isStreaming = ref(false)
  const streamContainerRef = ref<HTMLElement>()

  /** 滚动 stream 容器到底部（nextTick 等待 DOM 更新后再滚）。 */
  function scrollStreamToBottom() {
    nextTick(() => {
      const el = streamContainerRef.value
      if (el) el.scrollTop = el.scrollHeight
    })
  }

  function addStreamMsg(msg: Omit<StreamMessage, 'timestamp'>) {
    // 过滤 thinking 类型中的 <think> 标签
    const cleaned = { ...msg }
    if (cleaned.type === 'thinking' && cleaned.content) {
      cleaned.content = cleanThinkTags(cleaned.content)
      if (!cleaned.content) return // 过滤后为空则不添加
    }
    // thinking 消息默认展开（collapsed 未设置时初始化为 false）
    if (cleaned.type === 'thinking' && cleaned.collapsed === undefined) {
      cleaned.collapsed = false
    }
    // 思考过程出现时，隐藏所有还在进行中的步骤状态消息
    if (cleaned.type === 'thinking') {
      streamMessages.value.forEach(m => {
        if (m.type === 'status' && !m.stepDone && !m.hidden) {
          m.hidden = true
        }
      })
    }
    streamMessages.value.push({ ...cleaned, timestamp: Date.now() })
    scrollStreamToBottom()
  }

  function appendToLastThinking(text: string) {
    // delta 中也可能包含 <think> 标签片段，先追加再定期清理
    const msgs = streamMessages.value
    if (msgs.length > 0 && msgs[msgs.length - 1].type === 'thinking') {
      msgs[msgs.length - 1].content += text
      // 每次追加后清理标签（标签可能跨多个 delta 到达）
      msgs[msgs.length - 1].content = msgs[msgs.length - 1].content
        .replace(/<\/?think>/gi, '')
    } else {
      addStreamMsg({ type: 'thinking', content: text })
    }
    scrollStreamToBottom()
  }

  function appendToLastCommand(text: string) {
    const msgs = streamMessages.value
    if (msgs.length > 0 && msgs[msgs.length - 1].type === 'command') {
      msgs[msgs.length - 1].content += text
    } else {
      addStreamMsg({ type: 'command', content: text })
    }
    scrollStreamToBottom()
  }

  /** 把所有匹配 stepKey 且未完成的 status 消息更新为 badge（防止 SSE 重复事件导致残留） */
  function completeStepMsg(stepKey: string, badgeText: string) {
    streamMessages.value
      .filter(m => m.stepKey === stepKey && !m.stepDone)
      .forEach(m => { m.content = badgeText; m.stepDone = true })
  }

  /** 添加步骤进行中消息，若已存在相同 stepKey 的未完成消息则跳过 */
  function addStepRunningMsg(content: string, stepKey: string) {
    const exists = streamMessages.value.some(m => m.stepKey === stepKey && !m.stepDone)
    if (!exists) addStreamMsg({ type: 'status', content, stepKey })
  }

  function restoreReplayStreamMessages(messages: ReplayStreamMessage[]) {
    const restored: StreamMessage[] = []
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i]
      const next = messages[i + 1]
      const content = msg.content || ''

      // 跳过已有完成消息覆盖的进行中步骤
      if (msg.type === 'status' && replayIsRunning(content)) continue
      // 旧数据中的工具执行结果（如 "✅ Successfully wrote..."）— 跳过，文件卡片已表达
      if (msg.type === 'status' && isToolResultMsg(content)) continue

      // 将紧跟在 tool 消息后的 ✅ 状态结果合并到 tool 消息中
      if (msg.type === 'tool' && next?.type === 'status' && (next.content?.startsWith('✅') || next.content?.startsWith('\u2705'))) {
        restored.push({
          type: 'tool',
          content,
          result: next.content.replace(/^✅\s*/, ''),
          resultCollapsed: true,
          timestamp: msg.timestamp || Date.now() + i,
        })
        i++
        continue
      }

      // 步骤完成消息 → 还原为 badge（优先使用已存储的 stepDone 标记）
      if (msg.stepDone) {
        restored.push({
          type: 'status',
          content,
          stepDone: true,
          stepKey: msg.stepKey,
          timestamp: msg.timestamp || Date.now() + i,
        })
        continue
      }

      // 步骤完成消息 → 还原为 badge（兼容旧数据）
      const badgeText = msg.type === 'status' ? replayAsBadge(content) : null
      if (badgeText) {
        restored.push({
          type: 'status',
          content: badgeText,
          stepDone: true,
          timestamp: msg.timestamp || Date.now() + i,
        })
        continue
      }

      restored.push({
        type: msg.type as StreamMessage['type'],
        content,
        fileName: msg.fileName,
        fileContent: msg.fileContent,
        collapsed: msg.collapsed,
        hidden: msg.hidden,
        attachments: msg.attachments,
        timestamp: msg.timestamp || Date.now() + i,
      })
    }
    // append 而非覆盖：允许调用方（如 loadConversationHistory）在 restore 之前
    // 预先插入 brainstorm 阶段消息；如果调用方需要整体重置，在调用前自行置空即可
    streamMessages.value = [...streamMessages.value, ...restored]
    scrollStreamToBottom()
  }

  return {
    // state
    streamMessages,
    isStreaming,
    streamContainerRef,
    // methods
    scrollStreamToBottom,
    addStreamMsg,
    appendToLastThinking,
    appendToLastCommand,
    completeStepMsg,
    addStepRunningMsg,
    restoreReplayStreamMessages,
  }
}

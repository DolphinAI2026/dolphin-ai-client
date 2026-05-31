<!-- FormDesignerPanel.vue — 表单 业务视角 preview + iframe edit (design-v4 R).

  2026-05-27 R: 按 SPEC 重构. 业务视角 + 对话 = 我们做; 手动改 = iframe apaas 原生.

  保留:
    - preview mode 全套 (业务视角 — 真表单 grid + FormPreviewInput inline render)
    - view-mode toggle (预览 / 编辑)
    - 标题 + form_id + 字段计数 header
    - 用对话改 CTA (preview), AI 助手 (preview)
    - 保存 按钮 (preview 时 disabled, 因为 iframe 内部自己保存)
    - 字段类型 / 组件映射表 (preview 渲染用)
  删:
    - 3 列 builder layout (左库 + 中央卡片 + 右属性)
    - vuedraggable + 字段属性面板 + 拖排
    - dirty/pending tracking / 保存 batch (走 iframe 后, apaas 自己存)
    - 字段 model 拉取 logic (preview 只读, 走 components endpoint 拿数据)
  新:
    - viewMode === 'edit' 时渲染 <ApaasEmbedIframe>
      menuType='MODEL', mode='config' (默认), apaas 原生 fn-config 编辑器.

  Props 跟旧版兼容 (appId/menuId/menuName/formId).
-->
<template>
  <section class="fbp" aria-label="表单设计器">
    <!-- 空态 1: 未选菜单 -->
    <EmptyState
      v-if="!menuId"
      title="选择一个表单"
      desc="从左侧菜单列表点击某个表单, 这里显该表单的字段设计."
    >
      <template #icon>📝</template>
    </EmptyState>

    <!-- 空态 2: 加载中 (preview mode) -->
    <SkeletonCard v-else-if="loading && viewMode === 'preview'" :lines="6" />

    <!-- 空态 3: 错误 (preview mode) -->
    <div v-else-if="error && viewMode === 'preview'" class="fbp-state fbp-state-err">
      <div class="fbp-state-icon">⚠️</div>
      <p>{{ error }}</p>
      <button class="fbp-btn fbp-btn-ghost" @click="reload">重试</button>
    </div>

    <!-- preview / edit shell -->
    <div v-else class="fbp-shell">
      <!-- ─── header (预览 + 编辑共用) — 2026-05-27 S: 删 title/form_id 重复, 上面 mdsh-subnav 已有 -->
      <header class="fbp-canvas-head">
        <div class="fbp-canvas-meta">
          <p class="fbp-canvas-sub">
            <span v-if="modelCode" class="fbp-code mono">{{ modelCode }}</span>
            <span v-if="fields.length" class="fbp-canvas-stat">{{ fields.length }} 字段</span>
            <span v-if="fields.filter(f => f.required).length" class="fbp-canvas-stat">
              {{ fields.filter(f => f.required).length }} 必填
            </span>
          </p>
        </div>
        <div class="fbp-canvas-actions">
          <!-- view/edit mode segmented toggle -->
          <div class="fbp-mode-toggle" role="group" aria-label="切换视图模式">
            <button
              class="fbp-mode-btn"
              :class="{ active: viewMode === 'preview' }"
              title="业务视角 — 看真表单"
              @click="viewMode = 'preview'"
            >
              <span aria-hidden="true">👁</span> 预览
            </button>
            <button
              class="fbp-mode-btn"
              :class="{ active: viewMode === 'edit' }"
              title="跳到 apaas 原生编辑器手动改"
              @click="viewMode = 'edit'"
            >
              <span aria-hidden="true">✏️</span> 编辑
            </button>
          </div>
          <!-- 2026-05-29: 删「用对话改」「保存」死按钮 — 二者只弹 alert/永久 disabled。
               改字段走常驻右栏「配置助手」或「编辑」模式(apaas 原生编辑器自带保存)。 -->
        </div>
      </header>

      <!-- ─── preview mode body ──────────────────────────────────────── -->
      <div v-if="viewMode === 'preview'" class="fbp-canvas-body fbp-canvas-body-preview">
        <div class="fbp-preview-banner">
          <span class="fbp-preview-banner-icon" aria-hidden="true">✨</span>
          <span>业务视角预览 — 看到的就是最终用户填表样子, 改字段请用配置助手对话, 或切到"编辑"模式进 apaas 原生编辑器手动调.</span>
        </div>
        <div class="fbp-form-preview">
          <!-- 2026-05-27 S: 删 preview-head 内部 title/modelCode/字段数 重复 (header 已有) -->
          <div v-if="fields.length === 0" class="fbp-form-preview-empty">
            <div class="fbp-canvas-empty-icon">🧩</div>
            <p>该表单暂无字段</p>
            <p class="hint">切到"编辑"模式进 apaas 原生编辑器添加, 或用配置助手对话生成</p>
          </div>
          <form v-else class="fbp-form-preview-grid" @submit.prevent="onPreviewSubmit">
            <div
              v-for="f in fields"
              :key="f.id"
              class="fbp-form-row"
              :class="{ 'fbp-form-row-full': isFullWidthWidget(f.type) }"
              @mouseenter="hoveredFieldId = f.id"
              @mouseleave="hoveredFieldId = ''"
            >
              <label class="fbp-form-label">
                {{ f.name || '未命名字段' }}
                <span v-if="f.required" class="fbp-form-req">*</span>
                <button
                  v-if="hoveredFieldId === f.id"
                  type="button"
                  class="fbp-form-edit-hint"
                  title="改字段请用配置助手对话"
                  @click="onInlineEditHint(f)"
                >改这个字段 →</button>
              </label>
              <FormPreviewInput :field="f" :model-value="formValues[f.code]" :app-id="props.appId" :form-id="props.formId || ''" @update:model-value="(v: any) => formValues[f.code] = v" />
              <p v-if="f.description" class="fbp-form-desc">{{ f.description }}</p>
            </div>
            <div class="fbp-form-actions">
              <button type="button" class="fbp-btn fbp-btn-ghost" @click="onPreviewCancel">取消</button>
              <button type="submit" class="fbp-btn fbp-btn-primary">
                <span aria-hidden="true">✓</span> 提交申请
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- ─── edit mode body — apaas 原生 iframe ─────────────────────── -->
      <div v-else class="fbp-canvas-body fbp-canvas-body-edit">
        <div class="fbp-edit-banner">
          <span class="fbp-edit-banner-icon" aria-hidden="true">✏️</span>
          <span>编辑模式 — apaas 平台原生表单编辑器. 改字段后请在 iframe 内点保存, 然后切回预览模式看效果.</span>
        </div>
        <ApaasEmbedIframe
          :app-id="props.appId"
          :menu-id="props.menuId"
          :form-id="props.formId"
          menu-type="MODEL"
          mode="config"
        />
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch, h, defineComponent, type PropType } from 'vue'
import request, { API_PREFIX } from '@/utils/request'
import ApaasEmbedIframe from './ApaasEmbedIframe.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'

/* ────────────────────────────────────────────────────────────────
   类型 — preview 渲染用 (FormPreviewInput)
   ──────────────────────────────────────────────────────────────── */

type FieldType = string

interface FieldOption {
  code: string
  name: string
}

interface FormField {
  id: string
  code: string
  name: string
  type: FieldType
  placeholder?: string
  required: boolean
  editable: boolean
  options?: FieldOption[]
  description?: string
  max_length?: number
  // 2026-05-28: 自开发组件 (FORM_CUSTOM_COMPONENT_*) — 保留 kind 给 preview 显
  // 例如 "OPENAPI_SSE_CHAT". 标准内置组件这个字段为空.
  customKind?: string
  // 自开发组件的声明式配置 (customComponentConfig) — 这些组件不是黑盒包,
  // 行为完全由 config 参数化 (apiUrl / welcomeText / quickButtonsText / stream...),
  // preview 用它真渲染组件 UI.
  customConfig?: Record<string, any>
  // 完整 bo_code (含 ~ 前的 model_code) — P2 自开发组件 chat 代理定位组件用.
  boCodeFull?: string
  // 2026-05-31: 子表 (FORM_WIDGET_SON_TABLE) — 列定义 + 关联子 model code.
  // preview 用它把子表渲染成真网格 (列头 + 行) 而非误导性单行文本框.
  subColumns?: { code: string; name: string; type: FieldType; required: boolean }[]
  subModelCode?: string
}

/* ────────────────────────────────────────────────────────────────
   apaas component_type → widget type 映射 (form/{form_id}/detail 用)
   ──────────────────────────────────────────────────────────────── */

const COMPONENT_TYPE_MAP: Record<string, FieldType> = {
  FORM_TEXT_INPUT: 'text', FORM_INPUT: 'text',
  FORM_TEXTAREA_INPUT: 'textarea', FORM_TEXTAREA: 'textarea',
  FORM_NUMBER_INPUT: 'number', FORM_NUMBER: 'number',
  FORM_AMOUNT_INPUT: 'money', FORM_AMOUNT: 'money',
  FORM_RICH_TEXT_INPUT: 'richtext', FORM_RICH_TEXT: 'richtext',
  FORM_PHONE_INPUT: 'phone', FORM_PHONE: 'phone', FORM_MOBILE: 'phone',
  FORM_EMAIL_INPUT: 'email', FORM_EMAIL: 'email',
  FORM_IDCARD_INPUT: 'idcard', FORM_IDCARD: 'idcard',
  FORM_DATEPICK_INPUT: 'datetime', FORM_DATEPICK: 'datetime',
  FORM_DATE_INPUT: 'datetime', FORM_DATETIME: 'datetime', FORM_DATE: 'datetime',
  FORM_TIME_INPUT: 'datetime',
  FORM_PEOPLE_SELECT: 'user', FORM_PEOPLE: 'user', FORM_USER_SELECT: 'user',
  FORM_DEPT_SELECT: 'dept', FORM_DEPT: 'dept', FORM_DEPARTMENT_SELECT: 'dept',
  FORM_RADIO_GROUP: 'radio', FORM_RADIO: 'radio',
  FORM_CHECKBOX_GROUP: 'multi_select', FORM_CHECKBOX: 'multi_select',
  FORM_SELECT_BOX: 'select', FORM_SELECT: 'select', FORM_DROPDOWN: 'select',
  FORM_DROPDOWN_SINGLE: 'select_single', FORM_SELECT_SINGLE: 'select_single',
  FORM_DICTIONARY: 'select',
  FORM_FILE_UPLOAD: 'file', FORM_FILE: 'file', FORM_ATTACHMENT: 'file',
  FORM_IMAGE_UPLOAD: 'static_image', FORM_IMAGE: 'static_image',
  FORM_REGION_ADDRESS: 'region', FORM_REGION: 'region', FORM_ADDRESS: 'region',
  FORM_LOCATION: 'location',
  FORM_HYPERLINK: 'hyperlink', FORM_LINK: 'hyperlink',
  FORM_SWITCH: 'switch', FORM_BOOLEAN: 'switch',
  FORM_DOCUMENT_NUMBER: 'serial_no', FORM_SERIAL_NO: 'serial_no',
  FORM_DATA_SELECT: 'data_select',
  FORM_DATA_SINGLE: 'data_single', FORM_DATA_SELECT_SINGLE: 'data_single',
  FORM_REF_FORM: 'ref_form', FORM_REFERENCE_FORM: 'ref_form',
  FORM_DATA_STAT: 'data_stat', FORM_DATA_STATISTICS: 'data_stat',
  FORM_CROSS_FIELD: 'cross_field', FORM_REFERENCE_FIELD: 'cross_field',
  FORM_BUTTON: 'form_button',
  FORM_SUBTABLE: 'subtable', FORM_SUB_TABLE: 'subtable',
  FORM_VIRTUAL_FIELD: 'virtual_field',
  FORM_CUSTOM_DEV: 'custom_dev', FORM_CUSTOM_DEVELOP: 'custom_dev',
  FORM_STATIC_TEXT: 'static_text', FORM_TEXT: 'static_text',
  FORM_STATIC_IMAGE: 'static_image',
  FORM_DIVIDER: 'divider', FORM_PLACEHOLDER: 'placeholder',
  FORM_COLLAPSE_LAYOUT: 'collapse_layout',
  FORM_TAB_LAYOUT: 'tab_layout', FORM_TABS: 'tab_layout',
  FORM_FRAME_LAYOUT: 'frame_layout',
  FORM_TEMPLATE_FILE: 'template_file',
  // 2026-05-31: 上面一批键名是早期臆造的 (FORM_SUBTABLE / FORM_AMOUNT_INPUT / ...),
  // apaas 实际下发的 componentType 用下面这批真名 — 对齐 backend lowcode_standards.py
  // _PLATFORM_COMPONENT_ALIASES (权威, 跟真实 detailPageConfigById 解析一致).
  // 漏了它们 → componentTypeToWidget 落默认 'text' → 子表/金额/地区等被渲成单行文本框.
  FORM_WIDGET_SON_TABLE: 'subtable',   // 子表 (用户报的渲染 bug 根因)
  FORM_MONEY_INPUT: 'money',           // 金额
  FORM_WIDGET_AREA: 'region',          // 地区地址
  FORM_WIDGET_LOCATION: 'location',    // 地理位置
  FORM_ASSOCIATION: 'ref_form',        // 关联表单
  FORM_DATE_PICKER: 'datetime',        // 日期时间
  FORM_SERIAL: 'serial_no',            // 单据号
  FORM_HYPERLINK_INPUT: 'hyperlink',   // 超链接
  FORM_ID_CARD: 'idcard',              // 身份证号
  FORM_DATA_SELECTOR: 'data_select',   // 数据选择
  FORM_DATA_SELECTOR_SINGLE: 'data_single', // 数据单选
  FORM_SELECT_INPUT_SINGLE: 'select',  // 下拉单选
  FORM_SELECT_INPUT: 'multi_select',   // 下拉多选
  FORM_SELECT_MULTI: 'multi_select',
  FORM_RADIO_INPUT: 'radio',           // 单选框
  FORM_CHECKBOX_INPUT: 'multi_select', // 复选框
  FORM_SWITCH_SELECT: 'switch',        // 开关
  FORM_UPLOAD: 'file',                 // 附件上传
}

// 2026-05-28: apaas 自开发组件统一前缀 FORM_CUSTOM_COMPONENT_* (如
// FORM_CUSTOM_COMPONENT_OPENAPI_SSE_CHAT). 全归到 custom_dev widget, preview
// 渲成"自开发组件"卡片而非误导性文本框.
const CUSTOM_COMPONENT_PREFIX = 'FORM_CUSTOM_COMPONENT_'

function componentTypeToWidget(t: string | undefined): FieldType {
  if (!t) return 'text'
  const up = String(t).toUpperCase().trim()
  if (up.startsWith(CUSTOM_COMPONENT_PREFIX)) return 'custom_dev'
  return COMPONENT_TYPE_MAP[up] || 'text'
}

// 抽 widget kind (去前缀) — 给 preview 卡片显. 不是自开发组件返空.
function customComponentKind(t: string | undefined): string {
  if (!t) return ''
  const up = String(t).toUpperCase().trim()
  if (up.startsWith(CUSTOM_COMPONENT_PREFIX)) return up.slice(CUSTOM_COMPONENT_PREFIX.length)
  return ''
}

const BACKEND_TYPE_MAP: Record<string, FieldType> = {
  string: 'text', text: 'text', varchar: 'text', char: 'text',
  big_text: 'textarea', long_text: 'textarea', textarea: 'textarea',
  rich_text: 'richtext', html: 'richtext',
  integer: 'number', int: 'number', bigint: 'number', long: 'number',
  number: 'number', decimal: 'number', float: 'number', double: 'number',
  money: 'money', currency: 'money', amount: 'money',
  date: 'date', datetime: 'datetime', date_time: 'datetime', timestamp: 'datetime',
  time: 'time', daterange: 'daterange', date_range: 'daterange', month: 'month',
  boolean: 'switch', bool: 'switch', tinyint: 'switch',
  dict: 'dict', dict_single: 'select', dict_multi: 'select_multi',
  select: 'select', radio: 'radio', checkbox: 'multi_select',
  ref: 'ref', reference: 'ref',
  user: 'user', employee: 'user', staff: 'user',
  dept: 'dept', department: 'dept', org: 'dept', role: 'role',
  file: 'file', attachment: 'file', upload: 'file',
  image: 'image', picture: 'image', img: 'image',
  json: 'textarea', object: 'textarea', color: 'color',
}

function backendTypeToWidget(t: string | undefined): FieldType {
  if (!t) return 'text'
  return BACKEND_TYPE_MAP[String(t).toLowerCase().replace(/_$/, '')] || 'text'
}

function needsOptions(t: FieldType): boolean {
  return ['select', 'select_multi', 'radio', 'multi_select', 'tag', 'select_single'].includes(t)
}

const FULL_WIDTH_WIDGETS = new Set<string>([
  'textarea', 'richtext',
  'static_text', 'static_image', 'divider', 'placeholder',
  'collapse_layout', 'tab_layout', 'frame_layout', 'template_file',
  'subtable', 'data_select', 'data_stat',
  'custom_dev',  // 2026-05-28: 自开发组件卡片占整行
])
function isFullWidthWidget(t: string): boolean {
  return FULL_WIDTH_WIDGETS.has(t)
}

let _uidCounter = 0
function nextId(): string {
  _uidCounter += 1
  return `fb_${Date.now().toString(36)}_${_uidCounter}`
}

/* ────────────────────────────────────────────────────────────────
   自开发组件渲染器 — OPENAPI_SSE_CHAT (apaas 内置可配"OpenAPI 流式对话")
   config 完全声明式, 真还原 UI (welcome / quick buttons / preview / input).
   ──────────────────────────────────────────────────────────────── */

// quickButtonsText 形态: "标签1|提示词1\n标签2|提示词2"
function parseQuickButtons(text: unknown): { label: string; prompt: string }[] {
  if (typeof text !== 'string' || !text.trim()) return []
  return text.split('\n').map(line => {
    const [label, ...rest] = line.split('|')
    return { label: (label || '').trim(), prompt: rest.join('|').trim() }
  }).filter(b => b.label)
}

// OPENAPI_SSE_CHAT 交互组件 — P2: 真发消息 + 流式收 (走 backend SSE 代理).
// 预览里能真用: 输入/快捷按钮 → POST /forms/{id}/custom-widget/chat → 逐字流式追加.
interface OacMessage { role: 'user' | 'assistant'; text: string }

const OpenApiSseChatPreview = defineComponent({
  name: 'OpenApiSseChatPreview',
  props: {
    appId: { type: Number, required: true },
    formId: { type: String, required: true },
    boCode: { type: String, default: '' },
    config: { type: Object as PropType<Record<string, any>>, default: () => ({}) },
  },
  setup(props) {
    const messages = ref<OacMessage[]>([])
    const inputText = ref('')
    const streaming = ref(false)
    const errorMsg = ref('')

    const cfg = props.config || {}
    const welcome = String(cfg.welcomeText || '你好，我可以接入指定 OpenAPI 并流式展示回复。')
    const placeholder = String(cfg.placeholder || '请输入要发送给接口的问题')
    const quickBtns = parseQuickButtons(cfg.quickButtonsText)
    const showPreview = cfg.showPreview !== false
    const showHeader = cfg.showHeader === true
    const previewHeight = Number(cfg.previewHeight) || 320
    const apiUrl = String(cfg.apiUrl || '')
    const method = String(cfg.method || 'POST').toUpperCase()
    const isStream = cfg.stream !== false
    const canChat = !!props.boCode && !!apiUrl

    async function send(text: string) {
      const msg = (text || '').trim()
      if (!msg || streaming.value || !canChat) return
      errorMsg.value = ''
      messages.value.push({ role: 'user', text: msg })
      const assistant: OacMessage = { role: 'assistant', text: '' }
      messages.value.push(assistant)
      streaming.value = true
      inputText.value = ''
      try {
        const token = localStorage.getItem('token') || ''
        const resp = await fetch(
          `${API_PREFIX}/applications/${props.appId}/forms/${props.formId}/custom-widget/chat`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ bo_code: props.boCode, input: msg }),
          },
        )
        if (!resp.ok || !resp.body) {
          throw new Error(`HTTP ${resp.status}`)
        }
        // 解析 SSE: event: token\ndata: {"text":"..."}
        const reader = resp.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buf = ''
        let curEvent = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop() || ''
          for (const line of lines) {
            const l = line.trimEnd()
            if (l.startsWith('event:')) {
              curEvent = l.slice(6).trim()
            } else if (l.startsWith('data:')) {
              const dataStr = l.slice(5).trim()
              if (curEvent === 'token') {
                try {
                  const obj = JSON.parse(dataStr)
                  if (obj.text) assistant.text += obj.text
                } catch { /* ignore partial */ }
              } else if (curEvent === 'error') {
                try { errorMsg.value = JSON.parse(dataStr).message || '调用失败' }
                catch { errorMsg.value = '调用失败' }
              }
            }
          }
        }
      } catch (e: any) {
        errorMsg.value = e?.message || '调用失败'
        if (!assistant.text) assistant.text = `（调用失败: ${errorMsg.value}）`
      } finally {
        streaming.value = false
      }
    }

    return () => {
      // 对话区: welcome + 历史消息气泡
      const bubbles: any[] = []
      if (messages.value.length === 0) {
        bubbles.push(h('div', { class: 'fbp-oac-welcome' }, welcome))
      } else {
        for (const m of messages.value) {
          bubbles.push(h('div', {
            class: ['fbp-oac-msg', m.role === 'user' ? 'fbp-oac-msg-user' : 'fbp-oac-msg-ai'],
          }, m.text || (streaming.value ? '…' : '')))
        }
      }

      const chatCol = h('div', { class: 'fbp-oac-chat-col' }, [
        showHeader ? h('div', { class: 'fbp-oac-chat-header' }, 'OpenAPI 流式对话') : null,
        h('div', { class: 'fbp-oac-chat-body' }, bubbles),
        errorMsg.value ? h('div', { class: 'fbp-oac-err' }, errorMsg.value) : null,
        quickBtns.length
          ? h('div', { class: 'fbp-oac-quick-row' },
              quickBtns.map(b => h('button', {
                class: 'fbp-oac-quick-btn',
                type: 'button',
                title: b.prompt,
                disabled: streaming.value || !canChat,
                onClick: () => send(b.prompt || b.label),
              }, b.label)))
          : null,
        h('div', { class: 'fbp-oac-input-row' }, [
          h('input', {
            class: 'fbp-oac-input',
            type: 'text',
            placeholder: canChat ? placeholder : '该组件未带 apiUrl, 无法交互',
            value: inputText.value,
            disabled: streaming.value || !canChat,
            onInput: (e: Event) => { inputText.value = (e.target as HTMLInputElement).value },
            onKeydown: (e: KeyboardEvent) => { if (e.key === 'Enter') send(inputText.value) },
          }),
          h('button', {
            class: 'fbp-oac-send',
            type: 'button',
            disabled: streaming.value || !canChat || !inputText.value.trim(),
            onClick: () => send(inputText.value),
          }, streaming.value ? '…' : '发送'),
        ]),
      ])

      const previewCol = showPreview
        ? h('div', { class: 'fbp-oac-preview-col', style: `min-height:${Math.min(previewHeight, 360)}px` }, [
            h('div', { class: 'fbp-oac-preview-title' }, '返回内容预览'),
            h('div', { class: 'fbp-oac-preview-hint' }, '等待接口返回文件或 HTML — 接口返回 `html` / `file_list` / `answer` 时这里渲染.'),
          ])
        : null

      return h('div', { class: 'fbp-oac' }, [
        h('div', { class: 'fbp-oac-head' }, [
          h('span', { class: 'fbp-oac-icon', 'aria-hidden': 'true' }, '⚡'),
          h('span', { class: 'fbp-oac-title' }, 'OpenAPI 流式对话'),
          h('span', { class: 'fbp-oac-kind' }, 'OPENAPI_SSE_CHAT'),
          canChat ? h('span', { class: 'fbp-oac-live' }, '● 可交互') : null,
        ]),
        h('div', { class: 'fbp-oac-stage' }, [chatCol, previewCol]),
        apiUrl
          ? h('div', { class: 'fbp-oac-meta' }, [
              h('span', { class: 'fbp-oac-meta-method' }, method),
              isStream ? h('span', { class: 'fbp-oac-meta-stream' }, 'SSE 流式') : null,
              h('span', { class: 'fbp-oac-meta-url' }, apiUrl),
            ])
          : null,
      ])
    }
  },
})

/* ────────────────────────────────────────────────────────────────
   FormPreviewInput — preview mode 真业务表单 widget
   ──────────────────────────────────────────────────────────────── */

const FormPreviewInput = {
  props: {
    field: { type: Object as PropType<FormField>, required: true },
    modelValue: { type: null as any, default: undefined },
    appId: { type: Number, default: 0 },
    formId: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  setup(props: { field: FormField; modelValue: any; appId: number; formId: string }, { emit }: { emit: (e: 'update:modelValue', v: any) => void }) {
    return () => {
      const f = props.field
      const v = props.modelValue
      const ph = f.placeholder || `请输入${f.name || ''}`
      const cls = 'fbp-fp-input'
      const onInput = (e: Event) => emit('update:modelValue', (e.target as HTMLInputElement).value)
      const opts = f.options || []
      switch (f.type) {
        case 'textarea':
        case 'richtext':
          return h('textarea', { class: cls, placeholder: ph, rows: 3, value: v ?? '', onInput })
        case 'number':
        case 'money':
        case 'rating':
        case 'slider':
          return h('input', { class: cls, type: 'number', placeholder: ph, value: v ?? '', onInput })
        case 'switch':
          return h('label', { class: 'fbp-fp-switch', 'data-on': v ? 'true' : 'false' }, [
            h('input', {
              type: 'checkbox',
              checked: !!v,
              onChange: (e: Event) => emit('update:modelValue', (e.target as HTMLInputElement).checked),
            }),
            h('span', { class: 'fbp-fp-switch-track' }, [h('span', { class: 'fbp-fp-switch-knob' })]),
          ])
        case 'select':
        case 'dict':
        case 'select_single':
          return h('select', { class: cls, value: v ?? '', onChange: (e: Event) => emit('update:modelValue', (e.target as HTMLSelectElement).value) }, [
            h('option', { value: '' }, ph || '请选择…'),
            ...opts.map(o => h('option', { value: o.code }, o.name || o.code)),
          ])
        case 'select_multi':
        case 'multi_select':
        case 'tag':
          return h('select', {
            class: cls,
            multiple: true,
            size: Math.min(4, Math.max(2, opts.length || 2)),
            onChange: (e: Event) => emit('update:modelValue', Array.from((e.target as HTMLSelectElement).selectedOptions).map(o => o.value)),
          }, opts.length === 0
            ? [h('option', { disabled: true }, '无选项 — 请用配置助手配置')]
            : opts.map(o => h('option', { value: o.code }, o.name || o.code)))
        case 'radio':
          return h('div', { class: 'fbp-fp-radio-group' }, opts.length === 0
            ? [h('span', { class: 'fbp-fp-empty-hint' }, '无选项 — 请用配置助手配置')]
            : opts.map(o => h('label', { class: 'fbp-fp-radio-item' }, [
                h('input', { type: 'radio', name: f.code, value: o.code, checked: v === o.code, onChange: () => emit('update:modelValue', o.code) }),
                h('span', null, o.name || o.code),
              ])))
        case 'date':
          return h('input', { class: cls, type: 'date', value: v ?? '', onInput })
        case 'time':
          return h('input', { class: cls, type: 'time', value: v ?? '', onInput })
        case 'datetime':
          return h('input', { class: cls, type: 'datetime-local', value: v ?? '', onInput })
        case 'daterange':
          return h('div', { class: 'fbp-fp-range' }, [
            h('input', { class: cls, type: 'date' }),
            h('span', { class: 'fbp-fp-range-sep' }, '→'),
            h('input', { class: cls, type: 'date' }),
          ])
        case 'month':
          return h('input', { class: cls, type: 'month', value: v ?? '', onInput })
        case 'user':
        case 'dept':
        case 'role':
          return h('div', { class: 'fbp-fp-pick' }, [
            h('span', { class: 'fbp-fp-pick-icon' }, f.type === 'user' ? '👤' : f.type === 'dept' ? '🏢' : '🛡'),
            h('input', { class: cls, type: 'text', placeholder: ph, value: v ?? '', onInput, style: 'border:none;background:transparent;padding:0;flex:1;' }),
          ])
        case 'image':
        case 'file':
          return h('label', { class: 'fbp-fp-upload' }, [
            h('span', { class: 'fbp-fp-upload-icon' }, f.type === 'image' ? '🖼' : '📎'),
            h('span', { class: 'fbp-fp-upload-text' }, f.type === 'image' ? '点击上传图片' : '点击上传文件'),
            h('input', { type: 'file', style: 'display:none' }),
          ])
        case 'phone':
          return h('input', { class: cls, type: 'tel', placeholder: ph || '请输入手机号', value: v ?? '', onInput })
        case 'email':
          return h('input', { class: cls, type: 'email', placeholder: ph || '请输入邮箱地址', value: v ?? '', onInput })
        case 'idcard':
          return h('input', { class: cls, type: 'text', placeholder: ph || '请输入证件号', value: v ?? '', onInput })
        case 'region':
          return h('input', { class: cls, type: 'text', placeholder: ph || '请选择省/市/区', value: v ?? '', onInput })
        case 'location':
          return h('input', { class: cls, type: 'text', placeholder: ph || '📍 点击定位', value: v ?? '', onInput })
        case 'hyperlink':
          return h('input', { class: cls, type: 'url', placeholder: ph || 'https://', value: v ?? '', onInput })
        case 'serial_no':
          return h('input', { class: cls, type: 'text', placeholder: 'SQDH-XXXX (自动生成)', value: v ?? '', readonly: true })
        case 'static_text':
          return h('div', { class: 'fbp-fp-static' }, f.placeholder || f.name || '')
        case 'static_image':
          return h('div', { class: 'fbp-fp-static-img' }, [h('span', null, '🖼 静态图片')])
        case 'divider':
          return h('hr', { class: 'fbp-fp-divider' })
        case 'placeholder':
          return h('div', { class: 'fbp-fp-placeholder' })
        case 'collapse_layout':
        case 'tab_layout':
        case 'frame_layout':
          return h('div', { class: 'fbp-fp-layout-hint' }, f.type === 'collapse_layout' ? '【折叠布局】' : f.type === 'tab_layout' ? '【分页布局】' : '【框架布局】')
        case 'form_button':
          return h('button', { class: 'fbp-btn fbp-btn-ghost fbp-btn-sm', type: 'button' }, f.name || '按钮')
        case 'subtable': {
          // 2026-05-31: 子表渲染成真网格 (列头 + 示例行 + 添加行占位), 而非误导性
          // 单行文本框. 列来自 c.table_column (apaas 已配置的子表列), 兜底子 model 字段.
          const cols = f.subColumns || []
          if (!cols.length) {
            return h('div', { class: 'fbp-fp-subtable fbp-fp-subtable-empty' }, [
              h('span', { class: 'fbp-fp-subtable-icon', 'aria-hidden': 'true' }, '📑'),
              h('span', null, '子表 — 暂无列定义 (apaas 未配置子表列)'),
            ])
          }
          return h('div', { class: 'fbp-fp-subtable' }, [
            h('div', { class: 'fbp-fp-subtable-scroll' }, [
              h('table', { class: 'fbp-fp-subtable-table' }, [
                h('thead', null, [
                  h('tr', null, [
                    h('th', { class: 'fbp-fp-subtable-idx' }, '#'),
                    ...cols.map(col => h('th', { key: col.code }, [
                      h('span', null, col.name),
                      col.required ? h('span', { class: 'fbp-fp-subtable-req' }, ' *') : null,
                    ])),
                  ]),
                ]),
                h('tbody', null, [
                  h('tr', null, [
                    h('td', { class: 'fbp-fp-subtable-idx' }, '1'),
                    ...cols.map(col => h('td', { key: col.code }, [
                      h('input', { class: 'fbp-fp-subtable-cell', type: 'text', placeholder: col.name, disabled: true }),
                    ])),
                  ]),
                ]),
              ]),
            ]),
            h('div', { class: 'fbp-fp-subtable-add', 'aria-hidden': 'true' }, `+ 添加一行 (共 ${cols.length} 列, 预览不可编辑)`),
          ])
        }
        case 'ref':
        case 'ref_form':
        case 'data_select':
        case 'data_single':
        case 'data_stat':
        case 'cross_field':
        case 'virtual_field':
        case 'template_file':
          return h('input', { class: cls, type: 'text', placeholder: ph || '关联数据 (点击选择)', value: v ?? '', onInput })
        case 'custom_dev': {
          // 2026-05-28: 自开发组件不是黑盒包 — config 完全声明式, 真渲染组件 UI.
          const cfg = f.customConfig || {}
          // ① OpenAPI 流式对话 — apaas 内置可配组件, 真还原 UI + 真交互 (P2)
          if (f.customKind === 'OPENAPI_SSE_CHAT') {
            return h(OpenApiSseChatPreview, {
              appId: props.appId,
              formId: props.formId,
              boCode: f.boCodeFull || '',
              config: cfg,
            })
          }
          // ② 其他自开发组件 — 暂无专属渲染器, 显 config 摘要卡片 (比纯占位强)
          return h('div', { class: 'fbp-fp-custom-dev' }, [
            h('div', { class: 'fbp-fp-custom-dev-head' }, [
              h('span', { class: 'fbp-fp-custom-dev-icon', 'aria-hidden': 'true' }, '✨'),
              h('span', { class: 'fbp-fp-custom-dev-title' }, '自开发组件'),
              f.customKind
                ? h('span', { class: 'fbp-fp-custom-dev-kind' }, f.customKind)
                : null,
            ]),
            Object.keys(cfg).length
              ? h('div', { class: 'fbp-fp-custom-dev-cfg' },
                  Object.entries(cfg).slice(0, 8).map(([k, val]) =>
                    h('div', { class: 'fbp-fp-custom-dev-cfg-row' }, [
                      h('span', { class: 'fbp-fp-custom-dev-cfg-k' }, k),
                      h('span', { class: 'fbp-fp-custom-dev-cfg-v' },
                        typeof val === 'string' ? val.slice(0, 60) : JSON.stringify(val).slice(0, 60)),
                    ])))
              : h('div', { class: 'fbp-fp-custom-dev-desc' }, '该自开发组件未带可读配置.'),
          ])
        }
        default:
          return h('input', { class: cls, type: 'text', placeholder: ph, value: v ?? '', onInput })
      }
    }
  },
}

/* ────────────────────────────────────────────────────────────────
   Props / state
   ──────────────────────────────────────────────────────────────── */

const props = defineProps<{
  appId: number
  menuId?: string
  menuName?: string
  formId?: string
}>()

const fields = ref<FormField[]>([])
const modelCode = ref('')
const loading = ref(false)
const error = ref('')

const viewMode = ref<'preview' | 'edit'>('preview')
const hoveredFieldId = ref<string>('')
const formValues = ref<Record<string, any>>({})

watch(() => props.formId, () => { formValues.value = {} })
watch(viewMode, () => { hoveredFieldId.value = '' })

function onPreviewSubmit() {
  alert('预览模式 — 提交不会真存. 改字段请用配置助手对话, 或切到"编辑"模式手动调.')
}
function onPreviewCancel() {
  formValues.value = {}
}
function onInlineEditHint(f: FormField) {
  alert(`请用右下角"配置助手"浮窗对话, 如:\n\n"把字段 ${f.name || f.code} 改成 XXX"\n"把 ${f.code} 改成必填"`)
}

/* ────────────────────────────────────────────────────────────────
   Data load (preview-only, components → fields)
   ──────────────────────────────────────────────────────────────── */

async function reload() {
  if (!props.appId || !props.menuId) {
    fields.value = []
    modelCode.value = ''
    return
  }
  loading.value = true
  error.value = ''
  modelCode.value = ''
  try {
    if (props.formId) {
      const respFD = await request.get<any, any>(
        `/applications/${props.appId}/forms/${props.formId}/detail`
      )
      if (respFD?.ok) {
        const comps = respFD.components || []
        fields.value = comps.map((c: any): FormField => {
          const compType = String(c.component_type || '')
          const widgetType = componentTypeToWidget(compType)
          const boCode = String(c.bo_code || '')
          const [_modelCode, fieldCode] = boCode.includes('~') ? boCode.split('~') : ['', boCode]
          if (_modelCode) modelCode.value = _modelCode
          const mm = (respFD.models || []).find((m: any) => m.model_code === _modelCode)
          const mf = mm?.fields?.find((x: any) => x.field_code === fieldCode)
          // 子表: 从 table_column 构建列 (model_field = modelCode.fieldCode);
          // 兜底 table_column 空时用关联子 model 的字段定义.
          let subColumns: FormField['subColumns']
          let subModelCode: string | undefined
          if (widgetType === 'subtable') {
            subModelCode = String(c.table_model_code || '') || undefined
            const rawCols: any[] = Array.isArray(c.table_column) ? c.table_column : []
            if (rawCols.length) {
              subColumns = rawCols.map((col: any) => {
                const mfRaw = String(col.model_field || '')
                const colCode = mfRaw.includes('.') ? mfRaw.split('.').pop() || '' : mfRaw
                return {
                  code: colCode || String(col.uuid || ''),
                  name: String(col.label || colCode || '列'),
                  type: componentTypeToWidget(String(col.component_type || '')),
                  required: !!col.required,
                }
              })
            } else if (subModelCode) {
              const subModel = (respFD.models || []).find((m: any) => m.model_code === subModelCode)
              subColumns = (subModel?.fields || []).map((sf: any) => ({
                code: String(sf.field_code || ''),
                name: String(sf.field_name || sf.field_code || '列'),
                type: backendTypeToWidget(sf.data_type),
                required: !!sf.required,
              }))
            }
          }
          return {
            id: nextId(),
            code: fieldCode || subModelCode || `field_${Math.random().toString(36).slice(2, 6)}`,
            name: String(c.label || fieldCode || '未命名'),
            type: widgetType,
            placeholder: '',
            required: !!c.required,
            editable: true,
            options: needsOptions(widgetType) ? [] : undefined,
            description: String(mf?.description || ''),
            max_length: mf?.max_length ? Number(mf.max_length) : undefined,
            customKind: customComponentKind(compType),
            customConfig: c.custom_component_config && typeof c.custom_component_config === 'object'
              ? c.custom_component_config as Record<string, any>
              : undefined,
            boCodeFull: boCode,
            subColumns,
            subModelCode,
          }
        })
        if (!modelCode.value) modelCode.value = String(respFD.main_model_code || '')
        return
      }
    }
    // 兜底: 走 section-content/models
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/section-content/models?with_fields=true`
    )
    if (resp?.ok) {
      const items: any[] = resp.items || []
      const target = items.find(it => {
        const raw = it.extra || {}
        return String(raw.model_id) === String(props.menuId)
          || String(raw.form_id) === String(props.formId)
          || (props.menuName && raw.model_name === props.menuName)
      })
      if (target) {
        const raw = target.extra || {}
        modelCode.value = raw.model_code || target.code || ''
        const rawFields = Array.isArray(raw.fields) ? raw.fields : []
        fields.value = rawFields.map((rf: any): FormField => {
          const wt = backendTypeToWidget(rf.data_type || rf.field_type)
          return {
            id: nextId(),
            code: rf.field_code || `field_${Math.random().toString(36).slice(2, 6)}`,
            name: rf.field_name || rf.field_code || '未命名',
            type: wt,
            placeholder: rf.placeholder || '',
            required: !!rf.required,
            editable: rf.editable !== false,
            options: Array.isArray(rf.options) ? rf.options.map((o: any) => ({
              code: String(o.code || o.value || ''),
              name: String(o.name || o.label || o.code || ''),
            })) : (needsOptions(wt) ? [] : undefined),
            description: String(rf.description || ''),
            max_length: rf.max_length ? Number(rf.max_length) : undefined,
          }
        })
      } else {
        fields.value = []
        modelCode.value = ''
      }
    } else {
      error.value = resp?.message || resp?.error_code || '加载失败'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    loading.value = false
  }
}

watch(() => [props.appId, props.menuId, props.formId], () => reload(), { immediate: true })
</script>

<style scoped>
.fbp {
  font-family: var(--font-sans);
  color: var(--text);
  background: var(--bg);
  height: 100%;
  display: flex;
  flex-direction: column;
  font-feature-settings: 'cv11', 'ss01';
  overflow: hidden;
}

/* ─── state (error 占位 — empty/loading 走共享 EmptyState / SkeletonCard) ─── */
.fbp-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  color: var(--text-3);
  gap: 12px;
  padding: var(--s-12) var(--s-4);
}
.fbp-state-icon { font-size: 40px; line-height: 1; }
.fbp-state p { margin: 0; font-size: 13.5px; }
.fbp-state-err { color: var(--err); }
.fbp-state-err .fbp-btn { margin-top: 8px; }

/* ─── shell ─────────────────────────────────────────────────── */
.fbp-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* ─── view-mode segmented toggle ────────────────────────────── */
.fbp-mode-toggle {
  display: inline-flex;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 2px;
  flex-shrink: 0;
}
.fbp-mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: transparent;
  border: 0;
  border-radius: 6px;
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
  font-family: inherit;
  white-space: nowrap;
}
.fbp-mode-btn:hover { color: var(--text); }
.fbp-mode-btn.active {
  background: var(--surface);
  color: var(--brand);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

/* ─── canvas header ─────────────────────────────────────────── */
.fbp-canvas-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  flex-shrink: 0;
  gap: 16px;
}
.fbp-canvas-meta { min-width: 0; flex: 1; }
.fbp-canvas-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.fbp-canvas-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-3);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.fbp-code {
  padding: 2px 6px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 11px;
  color: var(--text-2);
}
.fbp-canvas-sub > * + * { position: relative; }
.fbp-canvas-sub > * + *::before {
  content: '·';
  margin-right: 8px;
  color: var(--text-4);
}
.fbp-canvas-stat { font-size: 12px; }

.fbp-canvas-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ─── body ──────────────────────────────────────────────────── */
.fbp-canvas-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.fbp-canvas-body-preview {
  overflow: auto;
  padding: 0;
}
.fbp-canvas-body-edit {
  display: flex;
  flex-direction: column;
  background: var(--surface);
}

/* ─── preview banner ────────────────────────────────────────── */
.fbp-preview-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  background: var(--brand-soft, #eff6ff);
  color: var(--brand-text, var(--brand));
  font-size: 12px;
  border-bottom: 1px solid var(--brand-soft-2, var(--line));
}
.fbp-preview-banner-icon { font-size: 14px; }

.fbp-edit-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 12px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.fbp-edit-banner-icon { font-size: 14px; }

/* ─── 真业务表单 (preview mode) ─────────────────────────────── */
.fbp-form-preview {
  max-width: 720px;
  margin: 24px auto;
  padding: 0 24px 48px;
}
.fbp-form-preview-head {
  margin-bottom: 18px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
}
.fbp-form-preview-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.fbp-form-preview-sub {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-3);
  display: flex;
  gap: 10px;
  align-items: center;
}
.fbp-form-preview-empty {
  text-align: center;
  color: var(--text-3);
  padding: 48px 16px;
  font-size: 14px;
}
.fbp-form-preview-empty .hint {
  font-size: 12.5px;
  color: var(--text-4);
  margin-top: 4px;
}
.fbp-form-preview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 20px;
}
.fbp-form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
}
.fbp-form-row-full { grid-column: 1 / -1; }

.fbp-form-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-2);
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 18px;
}
.fbp-form-req {
  color: var(--err, #ef4444);
  font-weight: 500;
}
.fbp-form-edit-hint {
  margin-left: auto;
  background: transparent;
  border: 0;
  color: var(--brand);
  font-size: 11.5px;
  cursor: pointer;
  font-family: inherit;
  padding: 2px 4px;
  border-radius: 4px;
  transition: background 0.15s;
}
.fbp-form-edit-hint:hover {
  background: var(--brand-soft, #eff6ff);
}
.fbp-form-desc {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--text-4);
}
.fbp-form-actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}

/* responsive — narrow viewport preview 单列 */
@media (max-width: 640px) {
  .fbp-form-preview-grid { grid-template-columns: 1fr; }
}

/* ─── FormPreviewInput 真 widget 视觉 ─────────────────────── */
.fbp-fp-input {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text);
  background: var(--surface);
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s;
  box-sizing: border-box;
}
.fbp-fp-input:focus { border-color: var(--brand); }
.fbp-fp-input[readonly] { background: var(--surface-2); color: var(--text-3); }
textarea.fbp-fp-input { resize: vertical; min-height: 64px; font-family: inherit; }
select.fbp-fp-input { cursor: pointer; }

/* ─── 子表网格 (FORM_WIDGET_SON_TABLE) — 真表格预览 ─────────── */
.fbp-fp-subtable { width: 100%; }
.fbp-fp-subtable-scroll {
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.fbp-fp-subtable-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  color: var(--text);
}
.fbp-fp-subtable-table th {
  text-align: left;
  font-weight: 500;
  color: var(--text-3);
  background: var(--surface-2);
  padding: 7px 10px;
  white-space: nowrap;
  border-bottom: 1px solid var(--line);
}
.fbp-fp-subtable-table th:not(:last-child),
.fbp-fp-subtable-table td:not(:last-child) {
  border-right: 1px solid var(--line);
}
.fbp-fp-subtable-table td { padding: 4px 6px; }
.fbp-fp-subtable-idx {
  width: 36px;
  text-align: center;
  color: var(--text-4);
}
.fbp-fp-subtable-req { color: #e5484d; }
.fbp-fp-subtable-cell {
  width: 100%;
  min-width: 96px;
  padding: 5px 8px;
  border: 1px solid transparent;
  border-radius: 4px;
  font-size: 13px;
  color: var(--text);
  background: var(--surface);
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
}
.fbp-fp-subtable-cell:disabled { background: transparent; color: var(--text-3); cursor: not-allowed; }
.fbp-fp-subtable-add {
  display: block;
  padding: 7px 10px;
  font-size: 12px;
  color: var(--text-3);
  border: 1px dashed var(--line);
  border-top: none;
  border-radius: 0 0 6px 6px;
  text-align: center;
  user-select: none;
}
.fbp-fp-subtable-empty {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px;
  font-size: 13px;
  color: var(--text-3);
  border: 1px dashed var(--line);
  border-radius: 6px;
  background: var(--surface-2);
}
.fbp-fp-subtable-icon { font-size: 14px; }

.fbp-fp-radio-group {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 4px 0;
}
.fbp-fp-radio-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  cursor: pointer;
}
.fbp-fp-radio-item input[type=radio] { margin: 0; }
.fbp-fp-empty-hint { font-size: 12px; color: var(--text-4); font-style: italic; }

.fbp-fp-switch {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  position: relative;
}
.fbp-fp-switch input { display: none; }
.fbp-fp-switch-track {
  width: 32px;
  height: 18px;
  border-radius: 999px;
  background: var(--surface-3);
  transition: background 0.15s;
  position: relative;
  display: inline-block;
}
.fbp-fp-switch-knob {
  position: absolute;
  top: 2px; left: 2px;
  width: 14px; height: 14px;
  background: white;
  border-radius: 50%;
  box-shadow: 0 1px 2px rgba(0,0,0,0.2);
  transition: transform 0.15s;
}
.fbp-fp-switch[data-on=true] .fbp-fp-switch-track { background: var(--brand); }
.fbp-fp-switch[data-on=true] .fbp-fp-switch-knob { transform: translateX(14px); }

.fbp-fp-range {
  display: flex;
  align-items: center;
  gap: 6px;
}
.fbp-fp-range-sep { color: var(--text-3); font-size: 12px; }

.fbp-fp-pick {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  cursor: pointer;
}
.fbp-fp-pick-icon { font-size: 14px; }

.fbp-fp-upload {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border: 1px dashed var(--line);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text-3);
  cursor: pointer;
  font-size: 12.5px;
  transition: border-color 0.12s, background 0.12s;
}
.fbp-fp-upload:hover { border-color: var(--brand); background: var(--brand-soft, #eff6ff); }
.fbp-fp-upload-icon { font-size: 13px; }
.fbp-fp-upload-text { font-size: 12.5px; }

.fbp-fp-static {
  font-size: 13px;
  color: var(--text-2);
  padding: 6px 0;
}
.fbp-fp-static-img {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 80px;
  background: var(--surface-2);
  border-radius: 6px;
  color: var(--text-3);
  font-size: 12px;
}
.fbp-fp-divider {
  border: 0;
  border-top: 1px solid var(--line);
  margin: 8px 0;
}
.fbp-fp-placeholder {
  height: 16px;
}
.fbp-fp-layout-hint {
  padding: 12px;
  background: var(--surface-2);
  border-radius: 6px;
  color: var(--text-3);
  font-size: 12px;
  text-align: center;
}
/* 自开发组件 (custom-dev / OpenAPI 流式对话) 样式移到下方非 scoped <style> 块 —
   它们由 h() 在独立 defineComponent (OpenApiSseChatPreview) 里渲染, 是 SFC 的孙
   组件, 拿不到 scoped 的 data-v-xxx 作用域 ID, 所以必须全局 <style> 才生效. */

.fbp-canvas-empty-icon { font-size: 36px; line-height: 1; margin-bottom: 6px; }

/* ─── buttons ───────────────────────────────────────────────── */
.fbp-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: 0;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
  white-space: nowrap;
}
.fbp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.fbp-btn-ghost {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-2);
}
.fbp-btn-ghost:hover:not(:disabled) {
  border-color: var(--text-3);
  background: var(--surface-2);
}
.fbp-btn-primary {
  background: var(--brand);
  color: white;
}
.fbp-btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
}
.fbp-btn-sm {
  padding: 3px 8px;
  font-size: 11.5px;
}
.fbp-btn-icon { font-size: 13px; line-height: 1; }
.mono { font-family: var(--font-mono); }
</style>

<!-- 非 scoped — 自开发组件 (custom-dev / OpenApiSseChatPreview) 由 h() 在独立
     defineComponent 里渲染, 是 SFC 孙组件, 拿不到 scoped data-v 作用域 ID.
     类名 fbp-oac-/fbp-fp-custom-dev- 前缀够独特, 全局也安全. -->
<style>
/* 自开发组件预览卡片 (FORM_CUSTOM_COMPONENT_* 无专属渲染器时) */
.fbp-fp-custom-dev {
  padding: 14px 16px;
  border: 1px dashed var(--brand);
  border-radius: 8px;
  background: linear-gradient(180deg, rgba(29, 137, 168, 0.06), rgba(29, 137, 168, 0.02));
}
.fbp-fp-custom-dev-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.fbp-fp-custom-dev-icon { font-size: 14px; line-height: 1; }
.fbp-fp-custom-dev-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand);
}
.fbp-fp-custom-dev-kind {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 4px;
  background: rgba(29, 137, 168, 0.12);
  color: var(--brand);
  letter-spacing: 0.02em;
}
.fbp-fp-custom-dev-desc {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
}
.fbp-fp-custom-dev-cfg {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.fbp-fp-custom-dev-cfg-row {
  display: flex;
  gap: 8px;
  font-size: 11.5px;
}
.fbp-fp-custom-dev-cfg-k {
  flex: 0 0 110px;
  color: var(--text-3);
  font-family: var(--font-mono, ui-monospace, monospace);
}
.fbp-fp-custom-dev-cfg-v {
  flex: 1;
  color: var(--text-2);
  word-break: break-all;
}

/* ─── OpenAPI 流式对话 自开发组件 真渲染 ─────────────────────── */
.fbp-oac {
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface);
}
.fbp-oac-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  background: linear-gradient(90deg, rgba(29, 137, 168, 0.10), rgba(29, 137, 168, 0.02));
  border-bottom: 1px solid var(--line);
}
.fbp-oac-icon { font-size: 13px; line-height: 1; }
.fbp-oac-title { font-size: 13px; font-weight: 600; color: var(--brand); }
.fbp-oac-kind {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(29, 137, 168, 0.12);
  color: var(--brand);
}
.fbp-oac-stage {
  display: flex;
  gap: 0;
}
.fbp-oac-chat-col {
  flex: 1 1 60%;
  display: flex;
  flex-direction: column;
  padding: 14px;
  min-width: 0;
}
.fbp-oac-chat-header {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 10px;
}
.fbp-oac-chat-body {
  flex: 1;
  min-height: 90px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
  overflow-y: auto;
  max-height: 260px;
}
.fbp-oac-welcome {
  background: var(--surface-2);
  border-radius: 10px;
  padding: 10px 13px;
  font-size: 12.5px;
  color: var(--text-2);
  max-width: 90%;
  line-height: 1.5;
}
.fbp-oac-msg {
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 12.5px;
  line-height: 1.5;
  max-width: 90%;
  white-space: pre-wrap;
  word-break: break-word;
}
.fbp-oac-msg-user {
  align-self: flex-end;
  background: var(--brand);
  color: var(--text-inverse);
}
.fbp-oac-msg-ai {
  align-self: flex-start;
  background: var(--surface-2);
  color: var(--text-2);
}
.fbp-oac-err {
  font-size: 11.5px;
  color: var(--err, #dc2626);
  margin: 4px 0;
}
.fbp-oac-live {
  font-size: 10.5px;
  color: var(--ok, #16a34a);
  margin-left: auto;
}
.fbp-oac-quick-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0;
}
.fbp-oac-quick-btn {
  padding: 4px 12px;
  border: 1px solid rgba(29, 137, 168, 0.30);
  background: rgba(29, 137, 168, 0.06);
  color: var(--brand);
  border-radius: 14px;
  font-size: 12px;
  cursor: pointer;
}
.fbp-oac-quick-btn:disabled { cursor: not-allowed; opacity: 0.6; }
.fbp-oac-input-row {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
.fbp-oac-input {
  flex: 1;
  padding: 7px 11px;
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  font-size: 12.5px;
  background: var(--surface);
  color: var(--text);
}
.fbp-oac-input:disabled { background: var(--surface-2); color: var(--text-3); }
.fbp-oac-send {
  padding: 0 16px;
  border: 0;
  border-radius: 7px;
  background: var(--brand);
  color: var(--text-inverse);
  font-size: 12.5px;
  cursor: pointer;
}
.fbp-oac-send:disabled { cursor: not-allowed; opacity: 0.5; }
.fbp-oac-preview-col {
  flex: 1 1 40%;
  border-left: 1px dashed var(--line-strong);
  padding: 14px;
  background: var(--surface-2);
  min-width: 0;
}
.fbp-oac-preview-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 8px;
}
.fbp-oac-preview-hint {
  font-size: 11.5px;
  color: var(--text-3);
  line-height: 1.5;
}
.fbp-oac-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 14px;
  border-top: 1px solid var(--line);
  background: var(--surface-2);
  font-size: 11px;
}
.fbp-oac-meta-method {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-weight: 600;
  color: var(--ok, #16a34a);
}
.fbp-oac-meta-stream {
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(29, 137, 168, 0.12);
  color: var(--brand);
}
.fbp-oac-meta-url {
  flex: 1;
  color: var(--text-3);
  font-family: var(--font-mono, ui-monospace, monospace);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

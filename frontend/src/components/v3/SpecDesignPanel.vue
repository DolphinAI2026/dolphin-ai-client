<!-- SpecDesignPanel.vue — design-v4 U3: SPEC 设计层 (跟"功能" tab 平行).

  设计 tab = 改 SPEC 文档 (长链: 改 1 处 → AI 把 SPEC 翻译成 apaas 配置改多处).
  跟"功能" tab (直接 iframe apaas 原生, 短链: 改 1 处 = 1 处) 平行.

  布局: 3 pane —
   - LEFT  nav-pane (240px):   10 章节, 4 分组
   - CENTER doc-pane (1fr):    markdown 风格章节渲染, hover 出"用对话改这段"
   - RIGHT chat-slot (360px):  P2 接 ConfigAssistant — MVP 显 placeholder

  数据来源 (MVP 复用现有 endpoint):
   - GET /applications/{appId}                                 — app 元数据
   - GET /applications/{appId}/section-content/roles           — 角色
   - GET /applications/{appId}/section-content/models?with_fields=true — 数据模型 + 字段
   - GET /applications/{appId}/section-content/dicts           — 字典
   - GET /applications/{appId}/section-content/menus           — 菜单
   - GET /applications/{appId}/section-content/processes       — 流程
   - GET /applications/{appId}/datasources                     — 数据源

  视觉 100% 跟 docs/internal/design-tab-mockup-2026-05-27.html 视图 ① 对齐.
  设计 token 完全用 design-v3-tokens.css (`var(--brand)` / `var(--surface)` 等).

  ⚠️ MVP 不接 chat / 不做版本对比 / "确认并生成" disabled (P2).
-->
<template>
  <section class="sdp" aria-label="SPEC 设计">
    <!-- ── 顶部 toolbar ────────────────────────────────────────────────── -->
    <div class="sdp-toolbar">
      <!-- 版本 pill -->
      <div class="version-pill" :title="draftHint">
        <span class="dot draft" aria-hidden="true"></span>
        <span class="version-pill-label">草稿</span>
        <span class="arrow" aria-hidden="true">▾</span>
      </div>
      <!-- mode pill (阅读 / 对比) -->
      <div class="mode-pill" role="tablist" aria-label="视图模式">
        <button class="active" role="tab" aria-selected="true">
          <span aria-hidden="true">📖</span> 阅读
        </button>
        <button
          role="tab"
          aria-selected="false"
          disabled
          title="P2 接入"
        >
          <span aria-hidden="true">🔍</span> 对比
        </button>
      </div>
      <div class="toolbar-divider" aria-hidden="true"></div>
      <button class="toolbar-btn" disabled title="P2 接入">
        <span aria-hidden="true">⬇</span> 导出 .md
      </button>
      <button class="toolbar-btn" disabled title="P2 接入">
        <span aria-hidden="true">📜</span> 历史
      </button>
      <div class="spacer"></div>
      <button
        class="apply-cta"
        disabled
        title="P2 接入 — 需 SPEC 改动后才能生成"
      >
        <span aria-hidden="true">✨</span> 确认并生成
      </button>
    </div>

    <!-- ── 3 pane shell ────────────────────────────────────────────────── -->
    <div class="sdp-shell">

      <!-- LEFT: chapter nav -->
      <nav class="sdp-nav-pane" aria-label="章节导航">
        <div
          v-for="group in CHAPTER_GROUPS"
          :key="group.key"
          class="nav-section"
        >
          <div class="nav-section-title">{{ group.title }}</div>
          <button
            v-for="ch in group.items"
            :key="ch.key"
            class="nav-item"
            :class="{ active: activeChapter === ch.key }"
            type="button"
            @click="onChapterClick(ch.key)"
          >
            <span class="num">{{ ch.num }}</span>
            <span class="label">{{ ch.title }}</span>
          </button>
        </div>
      </nav>

      <!-- CENTER: SPEC doc -->
      <main class="sdp-doc-pane" ref="docPaneRef">
        <!-- doc header -->
        <div class="doc-title-row">
          <h1 class="doc-title">{{ appName }}</h1>
          <div class="doc-meta">
            <span v-if="appCode" class="mono">{{ appCode }}</span>
            <template v-if="appCode"><span>·</span></template>
            <span>草稿</span>
            <span>·</span>
            <span>{{ lastFetchedLabel }}</span>
          </div>
        </div>

        <!-- 草稿提示 banner -->
        <div class="doc-version-banner" role="status">
          <span aria-hidden="true">⚠️</span>
          <span>
            这里渲染应用的 <strong>SPEC 文档</strong> — 跟"功能" tab 直接改 apaas
            不同, 设计 tab 改的是<strong>语义描述</strong>, 由 AI 把改动翻译成
            apaas 平台配置. 当前为 read-only 预览 (P2 接入编辑).
          </span>
        </div>

        <!-- loading -->
        <div v-if="loading" class="state-block">
          <div class="spinner" aria-hidden="true"></div>
          <span>加载 SPEC 中…</span>
        </div>

        <!-- error -->
        <div v-else-if="error" class="state-block state-err">
          <div class="state-icon" aria-hidden="true">⚠️</div>
          <p>{{ error }}</p>
          <button class="toolbar-btn" type="button" @click="reload">重试</button>
        </div>

        <!-- 章节内容 (load 完成后渲染) -->
        <template v-else>
          <section
            v-for="ch in CHAPTERS"
            :key="ch.key"
            :id="`sec-${ch.key}`"
            class="section"
            :ref="el => bindSectionRef(ch.key, el as HTMLElement | null)"
          >
            <div class="section-head">
              <h2>{{ ch.num }}、{{ ch.title }}</h2>
              <button
                class="section-edit-btn"
                type="button"
                @click="onEditChapter(ch.key)"
                title="P2 接入 — 用对话改这段 SPEC"
              >
                <span aria-hidden="true">✨</span> 用对话改这段
              </button>
            </div>

            <!-- 章节内容 (按 key 分发) -->
            <!-- 一、应用信息 -->
            <template v-if="ch.key === 'app_info'">
              <table class="spec-table">
                <thead>
                  <tr><th style="width: 28%">字段</th><th>值</th></tr>
                </thead>
                <tbody>
                  <tr><td>应用名称</td><td>{{ appName || '—' }}</td></tr>
                  <tr><td>应用编码</td><td><span class="mono">{{ appCode || '—' }}</span></td></tr>
                  <tr v-if="appDescription"><td>应用描述</td><td>{{ appDescription }}</td></tr>
                  <tr v-if="apaasAppIdShown">
                    <td>aPaaS 应用 ID</td>
                    <td><span class="mono">{{ apaasAppIdShown }}</span></td>
                  </tr>
                  <tr v-if="appCreatedAt">
                    <td>创建时间</td>
                    <td>{{ appCreatedAt }}</td>
                  </tr>
                </tbody>
              </table>
            </template>

            <!-- 二、角色与权限 -->
            <template v-else-if="ch.key === 'roles'">
              <div v-if="loadedRoles.length === 0" class="subsection-empty">
                尚未配置角色 — 用对话或去权限 tab 添加.
              </div>
              <table v-else class="spec-table">
                <thead>
                  <tr><th>角色名称</th><th>编码</th><th>说明</th></tr>
                </thead>
                <tbody>
                  <tr v-for="r in loadedRoles" :key="r.id">
                    <td>{{ r.name }}</td>
                    <td><span class="mono">{{ r.code || '—' }}</span></td>
                    <td>{{ describeExtra(r.extra, 'description') || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </template>

            <!-- 三、数据模型 -->
            <template v-else-if="ch.key === 'data_model'">
              <div v-if="loadedModels.length === 0" class="subsection-empty">
                尚未定义数据模型 — 用对话添加模型, 或去"功能"tab 选菜单看真实配置.
              </div>
              <div
                v-for="m in loadedModels"
                :key="m.id"
                class="subsection"
              >
                <h3>
                  {{ m.name }}
                  <span v-if="m.code" class="mono code-after-h3">({{ m.code }})</span>
                </h3>
                <table v-if="modelFields(m).length" class="spec-table">
                  <thead>
                    <tr>
                      <th>字段名</th>
                      <th>code</th>
                      <th>类型</th>
                      <th>必填</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="f in modelFields(m)" :key="String(f.code || f.id || f.name)">
                      <td>{{ f.name || '—' }}</td>
                      <td><span class="mono">{{ f.code || '—' }}</span></td>
                      <td><span class="type-chip">{{ f.type || '—' }}</span></td>
                      <td>
                        <span v-if="f.required" class="required-mark">*</span>
                        <span v-else class="muted">—</span>
                      </td>
                      <td>{{ f.description || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
                <div v-else class="subsection-empty">该模型未拉到字段详情.</div>
              </div>
            </template>

            <!-- 四、数据字典 -->
            <template v-else-if="ch.key === 'dict'">
              <div v-if="loadedDicts.length === 0" class="subsection-empty">
                尚未定义数据字典.
              </div>
              <div v-for="d in loadedDicts" :key="d.id" class="subsection">
                <h3>
                  {{ d.name }}
                  <span v-if="d.code" class="mono code-after-h3">({{ d.code }})</span>
                </h3>
                <table v-if="dictItems(d).length" class="spec-table">
                  <thead>
                    <tr><th>code</th><th>名称</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="di in dictItems(d)" :key="String(di.code || di.value || di.name)">
                      <td><span class="mono">{{ di.code || di.value || '—' }}</span></td>
                      <td>{{ di.name || di.label || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
                <div v-else class="subsection-empty subsection-empty-soft">字典项明细未拉到.</div>
              </div>
            </template>

            <!-- 五、菜单结构 -->
            <template v-else-if="ch.key === 'menus'">
              <div v-if="loadedMenus.length === 0" class="subsection-empty">
                尚未定义菜单.
              </div>
              <table v-else class="spec-table">
                <thead>
                  <tr>
                    <th>菜单名称</th>
                    <th>编码</th>
                    <th>类型</th>
                    <th>关联表单/页面</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="m in loadedMenus" :key="m.id">
                    <td>{{ m.name }}</td>
                    <td><span class="mono">{{ m.code || '—' }}</span></td>
                    <td>
                      <span class="type-chip">{{
                        describeExtra(m.extra, 'menu_type') || describeExtra(m.extra, 'type') || '—'
                      }}</span>
                    </td>
                    <td>
                      <span class="mono">{{
                        describeExtra(m.extra, 'form_id') || describeExtra(m.extra, 'page_url') || '—'
                      }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>

            <!-- 六、表单设计 (汇总,详情去"功能"tab) -->
            <template v-else-if="ch.key === 'form'">
              <div class="subsection-empty subsection-empty-soft">
                表单字段汇总在<strong>三、数据模型</strong>章节; 表单布局 / 必填规则
                / 字段权限请去"功能"tab 选菜单 → 表单设计 panel 查看真实配置.
              </div>
            </template>

            <!-- 七、列表设计 (汇总) -->
            <template v-else-if="ch.key === 'list'">
              <div class="subsection-empty subsection-empty-soft">
                列表视图 (查询条件 / 列配置 / 过滤器) 跟数据模型一一对应, 请去"功能"
                tab 选菜单 → 列表设计 panel 查看真实配置.
              </div>
            </template>

            <!-- 八、流程 & 事件 -->
            <template v-else-if="ch.key === 'process'">
              <div v-if="loadedProcesses.length === 0" class="subsection-empty">
                尚未定义流程 — 用对话添加流程, 或去"功能"tab 选菜单 → 流程设计.
              </div>
              <table v-else class="spec-table">
                <thead>
                  <tr>
                    <th>流程名称</th>
                    <th>编码</th>
                    <th>关联表单</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in loadedProcesses" :key="p.id">
                    <td>{{ p.name }}</td>
                    <td><span class="mono">{{ p.code || '—' }}</span></td>
                    <td>
                      <span class="mono">{{
                        describeExtra(p.extra, 'form_id') || describeExtra(p.extra, 'form_code') || '—'
                      }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>

            <!-- 九、集成 & 自开发 -->
            <template v-else-if="ch.key === 'integration'">
              <div class="subsection-empty subsection-empty-soft">
                自开发页面 (Vue CUSTOM 菜单) / API 集成 / Webhook 配置等. 当前
                MVP 仅汇总 — 详情去"功能"tab + CUSTOM 菜单查看 IDE 工作区.
              </div>
            </template>

            <!-- 十、数据源 -->
            <template v-else-if="ch.key === 'datasource'">
              <div v-if="datasourceNote" class="subsection-empty subsection-empty-soft">
                {{ datasourceNote }}
              </div>
              <table v-else-if="loadedDatasources.length" class="spec-table">
                <thead>
                  <tr>
                    <th>数据源名称</th>
                    <th>类型</th>
                    <th>连接</th>
                    <th>关联模型</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="ds in loadedDatasources" :key="ds.datasource_id || ds.name">
                    <td>{{ ds.name || '—' }}</td>
                    <td><span class="type-chip">{{ ds.type || '—' }}</span></td>
                    <td class="mono">
                      <template v-if="ds.host">{{ ds.host }}<template v-if="ds.port">:{{ ds.port }}</template></template>
                      <template v-else>—</template>
                    </td>
                    <td><span class="muted">{{ ds.model_count ?? 0 }}</span></td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="subsection-empty">尚未关联数据源.</div>
            </template>
          </section>
        </template>
      </main>

      <!-- RIGHT: chat slot (P2 接 ConfigAssistant) -->
      <aside class="sdp-chat-slot" aria-label="SPEC 对话助手">
        <div class="chat-empty-state">
          <div class="ic" aria-hidden="true">💬</div>
          <h3>用对话改 SPEC</h3>
          <p>点章节"✨ 用对话改这段"或顶部输入框, AI 会改 SPEC 草稿.</p>
          <p class="hint">P2 接入 — 当前为 read-only 预览.</p>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import request from '@/utils/request'

// ── props ──────────────────────────────────────────────────────────────
const props = defineProps<{
  appId: number
  apaasAppId?: string
}>()

// ── 章节定义 ────────────────────────────────────────────────────────────
type ChapterKey =
  | 'app_info'
  | 'roles'
  | 'data_model'
  | 'dict'
  | 'menus'
  | 'form'
  | 'list'
  | 'process'
  | 'integration'
  | 'datasource'

interface ChapterDef {
  key: ChapterKey
  title: string
  group: '基础' | '数据' | '功能' | '扩展'
  num: string
}

const CHAPTERS: ChapterDef[] = [
  { key: 'app_info',    title: '应用信息',      group: '基础', num: '一' },
  { key: 'roles',       title: '角色与权限',    group: '基础', num: '二' },
  { key: 'data_model',  title: '数据模型',      group: '数据', num: '三' },
  { key: 'dict',        title: '数据字典',      group: '数据', num: '四' },
  { key: 'menus',       title: '菜单结构',      group: '功能', num: '五' },
  { key: 'form',        title: '表单设计',      group: '功能', num: '六' },
  { key: 'list',        title: '列表设计',      group: '功能', num: '七' },
  { key: 'process',     title: '流程 & 事件',   group: '功能', num: '八' },
  { key: 'integration', title: '集成 & 自开发', group: '扩展', num: '九' },
  { key: 'datasource',  title: '数据源',        group: '扩展', num: '十' },
]

const CHAPTER_GROUPS = computed(() => {
  const groups: Array<{ key: string; title: string; items: ChapterDef[] }> = []
  for (const ch of CHAPTERS) {
    let g = groups.find(x => x.title === ch.group)
    if (!g) {
      g = { key: ch.group, title: ch.group, items: [] }
      groups.push(g)
    }
    g.items.push(ch)
  }
  return groups
})

// ── 数据接口 (跟 section-content endpoint 对齐) ──────────────────────────
interface SectionItem {
  id: string
  name: string
  code?: string | null
  extra?: Record<string, any>
}

interface SectionResp {
  ok: boolean
  items?: SectionItem[]
  total?: number
  error_code?: string
  message?: string
}

interface DatasourceItem {
  datasource_id?: string
  name?: string
  type?: string
  host?: string | null
  port?: number | null
  model_count?: number
}

// ── reactive state ─────────────────────────────────────────────────────
const loading = ref(true)
const error = ref('')
const lastFetchedAt = ref<Date | null>(null)
// 默认选中第三章 (数据模型) — 跟 mockup 截图一致
const activeChapter = ref<ChapterKey>('data_model')

const docPaneRef = ref<HTMLElement | null>(null)
const sectionRefs = ref<Record<string, HTMLElement | null>>({})
function bindSectionRef(key: string, el: HTMLElement | null) {
  sectionRefs.value[key] = el
}

// app 元数据
const appName = ref('')
const appCode = ref('')
const appDescription = ref('')
const appCreatedAt = ref('')

// section 数据
const loadedRoles = ref<SectionItem[]>([])
const loadedModels = ref<SectionItem[]>([])
const loadedDicts = ref<SectionItem[]>([])
const loadedMenus = ref<SectionItem[]>([])
const loadedProcesses = ref<SectionItem[]>([])
const loadedDatasources = ref<DatasourceItem[]>([])
const datasourceNote = ref('')

// ── computed display ──────────────────────────────────────────────────
const apaasAppIdShown = computed(() => props.apaasAppId || '')

const lastFetchedLabel = computed(() => {
  if (!lastFetchedAt.value) return '加载中…'
  const d = lastFetchedAt.value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

const draftHint = computed(() => 'MVP: 当前为 SPEC 只读预览, 编辑接 P2')

// ── 字段 / 字典项 解构 helpers ─────────────────────────────────────────
interface ModelField {
  id?: string
  name?: string
  code?: string
  type?: string
  required?: boolean
  description?: string
}

function modelFields(m: SectionItem): ModelField[] {
  const extra = m.extra || {}
  // backend with_fields=true → extra 含 fields[]
  const raw = (extra.fields || extra.components || extra.columns || []) as any[]
  if (!Array.isArray(raw)) return []
  return raw.map((f: any): ModelField => ({
    id: String(f.id || f.uuid || f.field_id || ''),
    name: String(f.field_name || f.label || f.name || ''),
    code: String(f.field_code || f.code || f.bo_code || ''),
    type: String(
      f.field_type || f.type || f.component_type || f.data_type || '',
    ).toUpperCase(),
    required: Boolean(f.required ?? f.is_required ?? false),
    description: String(f.description || f.comment || f.remark || ''),
  }))
}

interface DictEntry {
  code?: string
  value?: string
  name?: string
  label?: string
}

function dictItems(d: SectionItem): DictEntry[] {
  const extra = d.extra || {}
  const raw = (extra.items || extra.values || extra.options || []) as any[]
  if (!Array.isArray(raw)) return []
  return raw.map((x: any): DictEntry => ({
    code: x.code || x.value,
    value: x.value || x.code,
    name: x.name || x.label,
    label: x.label || x.name,
  }))
}

function describeExtra(extra: Record<string, any> | undefined, key: string): string {
  if (!extra) return ''
  const v = extra[key]
  if (v === null || v === undefined) return ''
  return String(v)
}

// ── 数据加载 ──────────────────────────────────────────────────────────
async function fetchSection(
  endpoint: string,
  fallback: SectionItem[] = [],
): Promise<SectionItem[]> {
  try {
    const resp = await request.get<any, SectionResp>(endpoint)
    if (resp?.ok && Array.isArray(resp.items)) return resp.items
  } catch {
    // 静默 — 一个 section 失败不阻塞整页
  }
  return fallback
}

async function fetchApp(): Promise<void> {
  try {
    const resp = await request.get<any, any>(`/applications/${props.appId}`)
    if (resp && typeof resp === 'object') {
      appName.value = String(resp.name || resp.app_name || `应用 ${props.appId}`)
      appCode.value = String(resp.app_code || resp.code || '')
      appDescription.value = String(resp.description || '')
      const ca = resp.created_at || resp.createdAt
      if (ca) {
        try {
          const dt = new Date(ca)
          appCreatedAt.value = isNaN(dt.getTime()) ? String(ca) : dt.toLocaleString()
        } catch { appCreatedAt.value = String(ca) }
      }
    }
  } catch {
    appName.value = `应用 ${props.appId}`
  }
}

async function fetchDatasources(): Promise<void> {
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/datasources`,
    )
    if (resp?.ok && Array.isArray(resp.items)) {
      loadedDatasources.value = resp.items as DatasourceItem[]
      datasourceNote.value = ''
    } else {
      loadedDatasources.value = []
      const code = String(resp?.error_code || '')
      if (code === 'APP_NOT_DEPLOYED') {
        datasourceNote.value = '应用尚未部署到 aPaaS 平台 — 部署后才能拉数据源.'
      } else if (code === 'TOOL_NOT_AVAILABLE') {
        datasourceNote.value = '后端数据源 API 尚未就绪.'
      } else if (resp?.message) {
        datasourceNote.value = String(resp.message)
      }
    }
  } catch (e: any) {
    loadedDatasources.value = []
    if (e?.response?.status === 404) {
      datasourceNote.value = '后端数据源接口未上线.'
    }
  }
}

async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const base = `/applications/${props.appId}`
    const [, roles, models, dicts, menus, processes] = await Promise.all([
      fetchApp(),
      fetchSection(`${base}/section-content/roles`),
      fetchSection(`${base}/section-content/models?with_fields=true`),
      fetchSection(`${base}/section-content/dicts`),
      fetchSection(`${base}/section-content/menus`),
      fetchSection(`${base}/section-content/processes`),
      fetchDatasources(),
    ])
    loadedRoles.value = roles
    loadedModels.value = models
    loadedDicts.value = dicts
    loadedMenus.value = menus
    loadedProcesses.value = processes
    lastFetchedAt.value = new Date()
  } catch (e: any) {
    error.value = e?.message || '加载 SPEC 失败'
  } finally {
    loading.value = false
  }
}

// ── 章节切换 ────────────────────────────────────────────────────────
function onChapterClick(key: ChapterKey) {
  activeChapter.value = key
  // 滚动到对应章节
  nextTick(() => {
    const el = sectionRefs.value[key]
    if (el && docPaneRef.value) {
      try {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      } catch {
        // 老浏览器兜底
        docPaneRef.value.scrollTop = el.offsetTop - 16
      }
    }
  })
}

function onEditChapter(key: ChapterKey) {
  // P2 占位 — 真接通后会发事件到 ConfigAssistant 注入 prompt
  activeChapter.value = key
  // 当前 MVP 仅切高亮 — 后续接 chat 事件
}

// ── lifecycle ──────────────────────────────────────────────────────
onMounted(() => {
  reload()
})

watch(
  () => props.appId,
  (v, ov) => {
    if (v && v !== ov) reload()
  },
)
</script>

<style scoped>
.sdp {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg);
  font-family: var(--font-sans);
  color: var(--text);
  overflow: hidden;
}

/* ── 顶部 toolbar ─────────────────────────────────────────────────── */
.sdp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.version-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
  font-weight: 500;
}
.version-pill .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.version-pill .dot.draft { background: var(--warn); }
.version-pill .arrow { color: var(--text-4); font-size: 11px; }
.version-pill-label { color: var(--text); }

.mode-pill {
  display: inline-flex;
  background: var(--surface-2);
  border-radius: 8px;
  padding: 2px;
  border: 1px solid var(--line);
}
.mode-pill button {
  padding: 4px 10px;
  background: transparent;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-3);
  cursor: pointer;
  font-family: inherit;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.mode-pill button.active {
  background: var(--surface);
  color: var(--brand);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}
.mode-pill button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.toolbar-divider {
  width: 1px;
  height: 20px;
  background: var(--line);
}
.toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.toolbar-btn:hover:not(:disabled) {
  background: var(--surface-2);
  border-color: var(--line-strong);
}
.toolbar-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.spacer { flex: 1; }

.apply-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--brand);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.apply-cta:hover:not(:disabled) { background: var(--brand-hover); }
.apply-cta:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ── 3 pane shell ─────────────────────────────────────────────────── */
.sdp-shell {
  display: grid;
  grid-template-columns: 240px 1fr 360px;
  flex: 1;
  min-height: 0;
  background: var(--bg);
  overflow: hidden;
}

/* ── LEFT: chapter nav ────────────────────────────────────────────── */
.sdp-nav-pane {
  background: var(--surface);
  border-right: 1px solid var(--line);
  overflow-y: auto;
  padding: 12px 0;
}
.nav-section { margin-bottom: 12px; }
.nav-section-title {
  padding: 4px 16px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-4);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.nav-item {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 8px 16px;
  color: var(--text);
  cursor: pointer;
  font-size: 13px;
  border-left: 3px solid transparent;
  background: transparent;
  border-top: none;
  border-right: none;
  border-bottom: none;
  text-align: left;
  font-family: inherit;
  transition: all 0.1s;
  gap: 6px;
}
.nav-item:hover { background: var(--surface-2); }
.nav-item.active {
  background: var(--brand-soft);
  color: var(--brand);
  border-left-color: var(--brand);
  font-weight: 500;
}
.nav-item .num {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-4);
  min-width: 24px;
}
.nav-item.active .num { color: var(--brand); }
.nav-item .label { flex: 1; }

/* ── CENTER: doc pane ─────────────────────────────────────────────── */
.sdp-doc-pane {
  overflow-y: auto;
  padding: 32px 56px;
  background: var(--surface);
  min-width: 0;
}
.doc-title-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.doc-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
}
.doc-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 12px;
}
.doc-meta .mono { color: var(--text-4); }

.doc-version-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  background: var(--warn-soft);
  border: 1px solid rgba(180, 83, 9, 0.30);
  border-radius: 8px;
  color: var(--warn);
  font-size: 13px;
  margin-bottom: 28px;
  line-height: 1.55;
}
.doc-version-banner strong { color: var(--warn); font-weight: 600; }

/* states */
.state-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 64px 16px;
  color: var(--text-3);
  font-size: 13px;
}
.state-block.state-err { color: var(--err); }
.state-icon { font-size: 40px; opacity: 0.75; }
.spinner {
  width: 18px; height: 18px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: sdp-spin 0.9s linear infinite;
}
@keyframes sdp-spin { to { transform: rotate(360deg); } }

/* ── section ─────────────────────────────────────────────────────── */
.section {
  margin-bottom: 36px;
  scroll-margin-top: 16px;
}
.section-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 16px;
  position: relative;
}
.section-head h2 {
  font-size: 17px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
}
.section-edit-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: transparent;
  border: 1px dashed var(--brand);
  color: var(--brand);
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s;
  font-family: inherit;
}
.section:hover .section-edit-btn { opacity: 1; }
.section-edit-btn:hover { background: var(--brand-soft); }
.section-edit-btn:focus-visible { opacity: 1; outline: 2px solid var(--brand); outline-offset: 1px; }

/* subsection */
.subsection { margin-bottom: 20px; }
.subsection h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin: 0 0 8px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.code-after-h3 {
  color: var(--text-4);
  font-weight: 400;
  font-size: 12px;
}
.subsection-empty {
  padding: 14px 16px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 12.5px;
  border-radius: 8px;
  border: 1px dashed var(--line-strong);
}
.subsection-empty-soft {
  background: var(--brand-soft);
  border-color: rgba(29, 78, 216, 0.20);
  color: var(--text-2);
}
.subsection-empty-soft strong {
  color: var(--brand);
  font-weight: 600;
}

/* table */
.spec-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
  background: var(--surface);
}
.spec-table thead th {
  background: var(--surface-2);
  padding: 8px 12px;
  text-align: left;
  font-weight: 600;
  color: var(--text-2);
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
}
.spec-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--surface-3);
  color: var(--text);
  vertical-align: top;
}
.spec-table tr:last-child td { border-bottom: none; }

.mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-3);
}
.required-mark { color: var(--err); font-weight: 600; }
.muted { color: var(--text-4); }

.type-chip {
  display: inline-block;
  padding: 1px 6px;
  background: var(--surface-3);
  border-radius: 4px;
  font-size: 11px;
  color: var(--text-2);
  font-family: var(--font-mono);
}

/* ── RIGHT: chat slot ────────────────────────────────────────────── */
.sdp-chat-slot {
  background: var(--surface);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
}
.chat-empty-state {
  text-align: center;
  max-width: 280px;
  color: var(--text-3);
}
.chat-empty-state .ic {
  font-size: 36px;
  margin-bottom: 12px;
  opacity: 0.75;
}
.chat-empty-state h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin: 0 0 8px;
}
.chat-empty-state p {
  font-size: 12.5px;
  line-height: 1.55;
  margin: 0 0 6px;
}
.chat-empty-state .hint {
  font-size: 11.5px;
  color: var(--text-4);
  margin-top: 12px;
}
</style>

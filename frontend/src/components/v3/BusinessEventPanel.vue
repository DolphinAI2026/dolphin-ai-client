<!-- BusinessEventPanel.vue — 应用级业务事件【只读】自渲面板.

  数据源: GET /applications/{app_id}/business-events
  (后端 business_events.py, 包 list_apaas_business_events MCP 工具.)

  纯只读: 不放任何"打开低代码后台"按钮 — 编辑入口在外层 tab 条, 不归本组件管.

  UI:
    - 顶部标题区: "业务事件" + 副标题.
    - 列表: 每个 event 一张卡 — event_name (主) / event_code (次, 灰) /
      触发类型胶囊 / status 胶囊 (ENABLE=启用 / DISABLE=停用) / target (动作链摘要) /
      last_update. 点卡片头展开看细节 (trigger 各字段 + extra 原始 JSON).
    - 状态: loading / error (resp.ok===false 或抛异常 → message + 重试) / empty.

  视觉跟 DataSchemaEditor.vue 一致 — 全走 token (--surface/--line/--text/--brand…),
  不硬编码颜色; class 前缀 bep-.
-->
<template>
  <section class="bep" aria-label="业务事件面板">
    <!-- 标题区 -->
    <header class="bep-head">
      <div class="bep-head-meta">
        <div class="bep-title-row">
          <h1 class="bep-title">业务事件</h1>
          <span v-if="!loading && !error && events.length" class="bep-badge bep-badge-count">
            {{ events.length }}
          </span>
        </div>
        <p class="bep-subtitle">
          应用级业务事件 · 只读, 编辑请用右上「打开低代码后台」
          <span v-if="props.menuName" class="bep-subtitle-menu">· {{ props.menuName }}</span>
        </p>
      </div>
    </header>

    <!-- loading -->
    <SkeletonCard v-if="loading" :lines="4" />

    <!-- error -->
    <ErrorCard
      v-else-if="error"
      level="err"
      title="加载失败"
      :message="error"
      :actions="[{ label: '重试', primary: true, onClick: reload }]"
    />

    <!-- empty -->
    <div v-else-if="!events.length" class="bep-empty">
      <div class="bep-empty-icon"><AppIcon name="zap" :size="40" /></div>
      <h3>暂无业务事件</h3>
      <p>该应用还没有配置业务事件. 需要时请进低代码后台添加, 或用配置助手对话.</p>
    </div>

    <!-- 列表 -->
    <ul v-else class="bep-list">
      <li
        v-for="ev in events"
        :key="ev.event_id || ev.event_name"
        class="bep-card"
        :class="{ 'is-open': isExpanded(ev) }"
      >
        <!-- 卡片头 (可点击展开) -->
        <button
          type="button"
          class="bep-card-head"
          :aria-expanded="isExpanded(ev)"
          @click="toggle(ev)"
        >
          <span class="bep-chevron" :class="{ open: isExpanded(ev) }">▸</span>
          <div class="bep-card-meta">
            <div class="bep-card-title-row">
              <span class="bep-event-name">{{ ev.event_name || '未命名事件' }}</span>
              <span v-if="ev.event_code" class="bep-event-code mono">{{ ev.event_code }}</span>
            </div>
            <div class="bep-card-tags">
              <span class="bep-pill bep-pill-type" :title="ev.event_type">
                {{ eventTypeLabel(ev.event_type) }}
              </span>
              <span
                class="bep-pill"
                :class="statusClass(ev.status)"
                :title="ev.status"
              >
                {{ statusLabel(ev.status) }}
              </span>
              <span v-if="ev.target" class="bep-target mono" :title="ev.target || ''">
                {{ ev.target }}
              </span>
            </div>
          </div>
          <span v-if="ev.last_update" class="bep-card-update">{{ ev.last_update }}</span>
        </button>

        <!-- 展开细节 -->
        <div v-if="isExpanded(ev)" class="bep-card-body">
          <dl v-if="hasTrigger(ev)" class="bep-detail-grid">
            <template v-if="ev.trigger?.form_id">
              <dt>触发表单</dt>
              <dd class="mono">{{ ev.trigger.form_id }}</dd>
            </template>
            <template v-if="ev.trigger?.boc_code">
              <dt>对象编码</dt>
              <dd class="mono">{{ ev.trigger.boc_code }}</dd>
            </template>
            <template v-if="ev.trigger?.field_code">
              <dt>触发字段</dt>
              <dd class="mono">{{ ev.trigger.field_code }}</dd>
            </template>
          </dl>
          <p v-else class="bep-detail-empty">无触发源信息.</p>

          <div v-if="hasExtra(ev)" class="bep-raw">
            <span class="bep-raw-label">原始数据</span>
            <pre class="bep-raw-pre mono">{{ prettyExtra(ev) }}</pre>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { applicationApi } from '@/api/application'
import type { BusinessEventItem } from '@/api/application'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import ErrorCard from '@/components/states/ErrorCard.vue'
import AppIcon from '@/components/common/AppIcon.vue'

const props = defineProps<{
  appId: number
  menuName?: string
}>()

const events = ref<BusinessEventItem[]>([])
const loading = ref(false)
const error = ref('')

// 展开态: 用本地 Set 存展开的 event_id
const expanded = ref<Set<string>>(new Set())

// ─── 触发类型友好中文映射 (未知值回退原文) ───────────────────────────────────
const EVENT_TYPE_LABELS: Record<string, string> = {
  EVENT_OPERATION: '操作事件',
  EVENT_BUTTON: '按钮事件',
  EVENT_VALUE_CHANGE: '字段变更事件',
  EVENT_EXT: '外部事件',
  EVENT_EXTERNAL: '外部事件',
}

function eventTypeLabel(t: string): string {
  if (!t) return '事件'
  return EVENT_TYPE_LABELS[t] || t
}

// ─── status 映射 ─────────────────────────────────────────────────────────────
function statusLabel(s: string): string {
  const up = String(s || '').toUpperCase()
  if (up === 'ENABLE') return '启用'
  if (up === 'DISABLE') return '停用'
  return s || '—'
}

function statusClass(s: string): string {
  const up = String(s || '').toUpperCase()
  if (up === 'ENABLE') return 'bep-pill-on'
  if (up === 'DISABLE') return 'bep-pill-off'
  return 'bep-pill-neutral'
}

// ─── 展开/折叠 ───────────────────────────────────────────────────────────────
function keyOf(ev: BusinessEventItem): string {
  return String(ev.event_id || ev.event_name || '')
}
function isExpanded(ev: BusinessEventItem): boolean {
  return expanded.value.has(keyOf(ev))
}
function toggle(ev: BusinessEventItem): void {
  const k = keyOf(ev)
  const next = new Set(expanded.value)
  if (next.has(k)) next.delete(k)
  else next.add(k)
  expanded.value = next
}

// ─── 细节渲染 helper ─────────────────────────────────────────────────────────
function hasTrigger(ev: BusinessEventItem): boolean {
  const t = ev.trigger
  return !!(t && (t.form_id || t.boc_code || t.field_code))
}
function hasExtra(ev: BusinessEventItem): boolean {
  const e = ev.extra
  return !!(e && typeof e === 'object' && Object.keys(e).length > 0)
}
function prettyExtra(ev: BusinessEventItem): string {
  try {
    return JSON.stringify(ev.extra ?? {}, null, 2)
  } catch {
    return String(ev.extra)
  }
}

// ─── 加载 ───────────────────────────────────────────────────────────────────
async function reload(): Promise<void> {
  if (!props.appId) {
    events.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const resp = await applicationApi.getBusinessEvents(props.appId)
    if (resp?.ok) {
      events.value = Array.isArray(resp.items) ? resp.items : []
    } else {
      events.value = []
      error.value = resp?.message || resp?.error_code || '加载业务事件失败'
    }
  } catch (e: any) {
    events.value = []
    error.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    loading.value = false
  }
}

onMounted(reload)
watch(() => props.appId, () => {
  expanded.value = new Set()
  reload()
})
</script>

<style scoped>
.bep {
  font-family: var(--font-sans);
  color: var(--text);
  padding: 28px 36px;
  background: var(--bg);
  height: 100%;
  overflow-y: auto;
  font-feature-settings: 'cv11', 'ss01';
}

/* ─── 标题区 ─────────────────────────────────────────────────────────────── */
.bep-head {
  margin-bottom: 18px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}
.bep-head-meta {
  min-width: 0;
}
.bep-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.bep-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.3px;
}
.bep-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 999px;
  white-space: nowrap;
}
.bep-badge-count {
  background: var(--brand-soft);
  color: var(--brand);
  font-family: var(--font-mono);
}
.bep-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--text-3);
  line-height: 1.5;
}
.bep-subtitle-menu {
  color: var(--text-4);
}

/* ─── empty ──────────────────────────────────────────────────────────────── */
.bep-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 60px 24px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  color: var(--text-3);
  gap: 8px;
}
.bep-empty-icon { font-size: 40px; line-height: 1; }
.bep-empty h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.bep-empty p {
  margin: 0;
  font-size: 13px;
  max-width: 420px;
}

/* ─── 列表 ───────────────────────────────────────────────────────────────── */
.bep-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.bep-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
  transition: border-color 0.12s;
}
.bep-card.is-open {
  border-color: var(--line-strong);
}

.bep-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 14px 16px;
  background: transparent;
  border: none;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s;
}
.bep-card-head:hover {
  background: var(--surface-2);
}

.bep-chevron {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-4);
  transition: transform 0.15s;
  transform: rotate(0deg);
}
.bep-chevron.open {
  transform: rotate(90deg);
  color: var(--brand);
}

.bep-card-meta {
  flex: 1;
  min-width: 0;
}
.bep-card-title-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.bep-event-name {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--text);
}
.bep-event-code {
  font-size: 12px;
  color: var(--text-4);
  font-family: var(--font-mono);
}
.bep-card-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.bep-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: 11.5px;
  font-weight: 500;
  border-radius: 6px;
  white-space: nowrap;
  line-height: 1.4;
}
.bep-pill-type {
  background: var(--brand-soft);
  color: var(--brand);
}
.bep-pill-on {
  background: var(--ok-soft);
  color: var(--ok);
}
.bep-pill-off {
  background: var(--surface-3);
  color: var(--text-3);
}
.bep-pill-neutral {
  background: var(--surface-3);
  color: var(--text-3);
}
.bep-target {
  font-size: 12px;
  color: var(--text-3);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 280px;
}

.bep-card-update {
  flex-shrink: 0;
  font-size: 11.5px;
  color: var(--text-4);
  font-family: var(--font-mono);
  white-space: nowrap;
}

/* ─── 展开细节 ───────────────────────────────────────────────────────────── */
.bep-card-body {
  padding: 4px 16px 16px 40px;
  border-top: 1px solid var(--line);
}
.bep-detail-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 16px;
  margin: 12px 0 0;
}
.bep-detail-grid dt {
  font-size: 12.5px;
  color: var(--text-3);
  white-space: nowrap;
}
.bep-detail-grid dd {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-2);
  word-break: break-all;
}
.bep-detail-empty {
  margin: 12px 0 0;
  font-size: 12.5px;
  color: var(--text-4);
}

.bep-raw {
  margin-top: 14px;
}
.bep-raw-label {
  display: block;
  margin-bottom: 6px;
  font-size: 11.5px;
  color: var(--text-4);
  font-weight: 500;
}
.bep-raw-pre {
  margin: 0;
  padding: 12px 14px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow: auto;
}

/* mono 类 */
.mono {
  font-family: var(--font-mono);
}
</style>

<template>
  <section class="health-panel" aria-label="应用体检">
    <header class="health-head">
      <div class="health-title">
        <h2>应用体检</h2>
        <span v-if="report?.as_of">体检时间 {{ formatTime(report.as_of) }} · 引擎 v{{ report?.engine_version }}</span>
        <span v-else>确定性体检 · 配置 + 运行健康度</span>
      </div>
      <button class="health-refresh" type="button" :disabled="loading" @click="reload">
        <AppIcon name="refresh" :size="14" />
        <span>{{ loading ? '体检中…' : '重新体检' }}</span>
      </button>
    </header>

    <div v-if="loading" class="health-state">
      <div class="health-spinner" />
      <span>正在体检（并发拉取应用结构）…</span>
    </div>

    <div v-else-if="error" class="health-state is-error">
      <AppIcon name="warning" :size="16" />
      <span>{{ error }}</span>
      <button class="health-retry" type="button" @click="reload">重试</button>
    </div>

    <template v-else-if="report">
      <div class="health-overview">
        <div class="score-block" :data-grade="report.grade">
          <strong>{{ report.total_score ?? '—' }}</strong>
          <span>{{ report.grade }}</span>
        </div>
        <div class="overview-meta">
          <em v-if="report.has_critical" class="critical-badge">有高优风险</em>
          <p v-if="report.total_score === null">数据源全部不可用，暂无法体检。</p>
          <p v-else>{{ summaryLine }}</p>
          <div v-if="naDims.length" class="na-note">未参与评分（数据不可用）：{{ naDims.join('、') }}</div>
        </div>
      </div>

      <div class="dim-grid" aria-label="维度记分卡">
        <div
          v-for="d in report.dimensions"
          :key="d.dimension"
          class="dim-card"
          :class="{ 'is-na': d.na }"
          :data-band="d.na ? 'na' : bandOf(d.score)"
        >
          <span class="dim-name">{{ dimLabel(d.dimension) }}</span>
          <strong v-if="!d.na">{{ Math.round(d.score ?? 0) }}</strong>
          <strong v-else class="na">N/A</strong>
          <em>{{ d.na ? '数据不可用' : '权重 ' + Math.round(d.weight_used * 100) + '%' }}</em>
        </div>
      </div>

      <div class="findings" aria-label="问题与建议">
        <div class="findings-head">问题与建议（{{ report.findings.length }}）</div>
        <div v-if="!report.findings.length" class="health-state">未发现问题</div>
        <article
          v-for="(f, i) in report.findings"
          :key="f.check_id + i"
          class="finding"
          :data-severity="f.severity"
        >
          <em class="sev-chip">{{ severityLabel(f.severity) }}</em>
          <div class="finding-body">
            <strong>{{ f.title }} · {{ dimLabel(f.dimension) }}</strong>
            <p class="finding-detail">{{ f.detail }}</p>
            <p v-if="f.suggestion" class="finding-sug">建议：{{ f.suggestion }}</p>
          </div>
        </article>
      </div>
    </template>

    <div v-else class="health-state">点击「重新体检」开始</div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import request from '@/utils/request'

type Dimension = { dimension: string; score: number | null; na: boolean; weight_base: number; weight_used: number }
type Finding = { check_id: string; dimension: string; severity: string; title: string; detail: string; objects: string[]; suggestion: string }
type HealthReport = {
  total_score: number | null
  grade: string
  has_critical: boolean
  as_of?: string
  engine_version?: string
  dimensions: Dimension[]
  findings: Finding[]
  data_coverage: Record<string, boolean>
}

const props = defineProps<{ appId: number | string }>()

const DIM_LABELS: Record<string, string> = {
  menus: '菜单',
  models: '数据模型',
  dicts: '字典',
  roles: '角色',
  processes: '审批流程',
  events: '业务事件',
  deploy: '发布状态',
  activity: '活跃度',
}

const report = ref<HealthReport | null>(null)
const loading = ref(false)
const error = ref('')

const naDims = computed(() => (report.value?.dimensions || []).filter((d) => d.na).map((d) => dimLabel(d.dimension)))
const summaryLine = computed(() => {
  const r = report.value
  if (!r) return ''
  const high = r.findings.filter((f) => f.severity === 'high').length
  const total = r.findings.length
  if (!total) return '配置与运行检查全部通过。'
  return `共 ${total} 项待关注${high ? `，其中 ${high} 项高优` : ''}。`
})

async function reload() {
  if (!props.appId) return
  loading.value = true
  error.value = ''
  try {
    const resp = await request.get<any, any>(`/applications/${props.appId}/health`)
    if (!resp?.ok) throw new Error(resp?.message || '体检失败')
    const { ok, ...rest } = resp
    report.value = rest as HealthReport
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '体检失败'
    report.value = null
  } finally {
    loading.value = false
  }
}

function dimLabel(d: string) {
  return DIM_LABELS[d] || d
}

function bandOf(score: number | null) {
  if (score === null) return 'na'
  if (score >= 85) return 'good'
  if (score >= 55) return 'mid'
  return 'bad'
}

function severityLabel(s: string) {
  if (s === 'high') return '高优'
  if (s === 'medium') return '关注'
  return '提示'
}

function formatTime(ts?: string) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

watch(() => props.appId, () => reload())
onMounted(() => reload())
</script>

<style scoped>
.health-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 20px;
  color: var(--text);
  overflow-y: auto;
}
.health-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.health-title h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
}
.health-title span {
  display: block;
  margin-top: 3px;
  color: var(--text-3);
  font-size: 12px;
}
.health-refresh,
.health-retry {
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  border: 1px solid var(--brand);
  border-radius: 7px;
  background: var(--brand);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}
.health-refresh:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.health-retry {
  height: 28px;
  margin-left: 8px;
}

.health-overview {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}
.score-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 96px;
  padding: 10px 16px;
  border-radius: 10px;
  background: var(--surface-2);
}
.score-block strong {
  font-size: 34px;
  line-height: 1;
  font-weight: 700;
}
.score-block span {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-2);
}
.score-block[data-grade='健康'] strong { color: var(--ok); }
.score-block[data-grade='良好'] strong { color: var(--ok); }
.score-block[data-grade='中等'] strong { color: var(--warn); }
.score-block[data-grade='风险'] strong { color: var(--err); }
.score-block[data-grade='严重'] strong { color: var(--err); }
.overview-meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.critical-badge {
  align-self: flex-start;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--err-soft);
  color: var(--err);
  font-style: normal;
  font-size: 12px;
}
.overview-meta p {
  margin: 0;
  color: var(--text-2);
  font-size: 13px;
}
.na-note {
  color: var(--text-3);
  font-size: 12px;
}

.dim-grid {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(108px, 1fr));
  gap: 10px;
}
.dim-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.dim-card[data-band='bad'] { border-color: color-mix(in srgb, var(--err) 40%, var(--line)); }
.dim-card[data-band='mid'] { border-color: color-mix(in srgb, var(--warn) 38%, var(--line)); }
.dim-card.is-na { background: var(--surface-2); }
.dim-name {
  color: var(--text-3);
  font-size: 12px;
}
.dim-card strong {
  font-size: 22px;
  font-weight: 650;
}
.dim-card strong.na {
  font-size: 15px;
  color: var(--text-3);
}
.dim-card[data-band='good'] strong { color: var(--ok); }
.dim-card[data-band='mid'] strong { color: var(--warn); }
.dim-card[data-band='bad'] strong { color: var(--err); }
.dim-card em {
  font-style: normal;
  color: var(--text-3);
  font-size: 11px;
}

.findings {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.findings-head {
  color: var(--text-3);
  font-size: 12px;
  font-weight: 600;
}
.finding {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.finding[data-severity='high'] { border-color: color-mix(in srgb, var(--err) 40%, var(--line)); }
.finding[data-severity='medium'] { border-color: color-mix(in srgb, var(--warn) 36%, var(--line)); }
.sev-chip {
  align-self: start;
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-style: normal;
  font-size: 12px;
  background: var(--ok-soft);
  color: var(--ok);
  white-space: nowrap;
}
.finding[data-severity='high'] .sev-chip { background: var(--err-soft); color: var(--err); }
.finding[data-severity='medium'] .sev-chip { background: var(--warn-soft); color: var(--warn); }
.finding-body { min-width: 0; }
.finding-body strong {
  display: block;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
}
.finding-detail {
  margin: 3px 0 0;
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.5;
}
.finding-sug {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: 12px;
}

.health-state {
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
}
.health-state.is-error { color: var(--err); }
.health-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: health-spin 0.8s linear infinite;
}
@keyframes health-spin { to { transform: rotate(360deg); } }
</style>

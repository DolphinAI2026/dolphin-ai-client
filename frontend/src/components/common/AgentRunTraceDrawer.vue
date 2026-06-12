<template>
  <el-drawer
    v-model="open"
    title="Agent 活动 / Trace"
    direction="rtl"
    size="640px"
    :append-to-body="true"
    :destroy-on-close="true"
  >
    <div class="trace-wrap" v-loading="loading">
      <!-- run 列表 -->
      <div class="run-list">
        <div
          v-for="r in runs"
          :key="r.run_id"
          class="run-item"
          :class="{ active: r.run_id === selectedRunId }"
          @click="selectRun(r.run_id)"
        >
          <span class="run-status" :data-status="r.status">{{ statusLabel(r.status) }}</span>
          <span class="run-meta">{{ r.turn_count }} 轮 · {{ r.total_tokens }} tok</span>
          <span class="run-dur">{{ fmtMs(r.duration_ms) }}</span>
          <span class="run-time">{{ fmtTime(r.created_at) }}</span>
        </div>
        <div v-if="!runs.length && !loading" class="empty">本会话还没有 agent 运行记录</div>
      </div>

      <!-- 选中 run 的 step 时间线 -->
      <div v-if="detail" class="timeline">
        <div class="timeline-head">
          <span :data-status="detail.run.status" class="run-status">{{ statusLabel(detail.run.status) }}</span>
          <span>{{ detail.run.model || '—' }}</span>
          <span>{{ detail.run.total_prompt_tokens }} in / {{ detail.run.total_completion_tokens }} out</span>
          <span>{{ fmtMs(detail.run.duration_ms) }}</span>
        </div>
        <div v-if="detail.run.error_message" class="err-banner">{{ detail.run.error_message }}</div>

        <div v-for="s in detail.steps" :key="s.seq" class="step" :data-type="s.step_type">
          <div class="step-head">
            <span class="step-badge">{{ s.step_type }}</span>
            <span v-if="s.tool_name" class="step-tool">{{ s.tool_name }}</span>
            <span v-if="s.step_type === 'llm'" class="step-tok">
              {{ s.prompt_tokens ?? '?' }} in / {{ s.completion_tokens ?? '?' }} out
            </span>
            <span v-if="s.status" class="step-st" :data-status="s.status">{{ s.status }}</span>
            <span v-if="s.duration_ms != null" class="step-dur">{{ fmtMs(s.duration_ms) }}</span>
          </div>
          <pre v-if="s.args_json" class="step-body">{{ pretty(s.args_json) }}</pre>
          <pre v-if="s.result_text" class="step-body result">{{ truncate(s.result_text) }}</pre>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { agentObservabilityApi, type AgentRunSummary, type AgentRunDetail } from '@/api/agentObservability'

const props = defineProps<{
  modelValue: boolean
  sessionId: number | null
  preferRunId?: string | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const open = ref(props.modelValue)
const loading = ref(false)
const runs = ref<AgentRunSummary[]>([])
const detail = ref<AgentRunDetail | null>(null)
const selectedRunId = ref<string | null>(null)

watch(() => props.modelValue, (v) => {
  open.value = v
  if (v) void load()
})
watch(open, (v) => emit('update:modelValue', v))
// 抽屉已开着时再点另一条消息的「查看本次 trace」：只 tracePreferRunId 变、modelValue 不变，
// 上面那个 watcher 不会触发。这里补一个 —— 已加载到 runs 里就直接切到那条 run。
watch(() => props.preferRunId, (rid) => {
  if (open.value && rid && rid !== selectedRunId.value && runs.value.some(r => r.run_id === rid)) {
    void selectRun(rid)
  }
})

async function load() {
  if (!props.sessionId) { runs.value = []; detail.value = null; return }
  loading.value = true
  try {
    const res = await agentObservabilityApi.listRuns({ session_id: String(props.sessionId), limit: 50 })
    runs.value = res.runs || []
    const target = props.preferRunId && runs.value.some(r => r.run_id === props.preferRunId)
      ? props.preferRunId
      : (runs.value[0]?.run_id ?? null)
    if (target) await selectRun(target)
    else detail.value = null
  } catch (e: any) {
    ElMessage.error('加载 trace 失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function selectRun(runId: string) {
  selectedRunId.value = runId
  loading.value = true
  try {
    detail.value = await agentObservabilityApi.getRunDetail(runId)
  } catch (e: any) {
    ElMessage.error('加载 trace 详情失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function statusLabel(s: string) { return ({ success: '成功', error: '失败', running: '运行中', aborted: '已中止' } as any)[s] || s }
function fmtMs(ms: number | null) { return ms == null ? '—' : ms >= 1000 ? (ms / 1000).toFixed(1) + 's' : ms + 'ms' }
function fmtTime(t: string | null) { return t ? new Date(t).toLocaleString() : '—' }
function pretty(o: any) { try { return JSON.stringify(o, null, 2) } catch { return String(o) } }
function truncate(t: string) { return t.length > 4000 ? t.slice(0, 4000) + '\n…（已截断）' : t }
</script>

<style scoped>
.trace-wrap { display: flex; flex-direction: column; gap: 12px; height: 100%; overflow: hidden; }
.run-list { max-height: 30%; overflow-y: auto; border-bottom: 1px solid var(--t-border-soft, #e5e7eb); }
.run-item { display: flex; gap: 10px; align-items: center; padding: 7px 8px; font-size: 12.5px;
  cursor: pointer; border-radius: 6px; }
.run-item:hover { background: var(--t-bg-soft, #f3f4f6); }
/* active 用独立 token + 独立蓝色兜底，避免跟 hover 的 --t-bg-soft 解析成同色 */
.run-item.active { background: var(--t-bg-active, #dbe4ff); }
.run-meta, .run-dur, .run-time { color: var(--t-text-muted, #6b7280); }
.run-time { margin-left: auto; }
.run-status { font-weight: 600; }
.run-status[data-status="success"] { color: var(--ok); }
.run-status[data-status="error"] { color: var(--err); }
.run-status[data-status="running"] { color: var(--info); }
.timeline { flex: 1; overflow-y: auto; }
.timeline-head { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px;
  color: var(--t-text-secondary, #4b5563); padding: 6px 2px 10px; }
.err-banner { background: var(--err-soft); color: var(--err); padding: 8px 10px; border-radius: 6px;
  font-size: 12.5px; margin-bottom: 10px; }
.step { border: 1px solid var(--t-border-soft, rgba(116,128,171,0.14)); border-radius: 8px;
  padding: 8px 10px; margin-bottom: 8px; }
.step[data-type="tool"] { border-left: 3px solid var(--info); }
.step[data-type="llm"] { border-left: 3px solid #8b5cf6; }
.step-head { display: flex; gap: 10px; align-items: center; font-size: 12.5px; flex-wrap: wrap; }
.step-badge { text-transform: uppercase; font-size: 10.5px; letter-spacing: .04em;
  color: var(--t-text-muted, #6b7280); }
.step-tool { font-weight: 600; }
.step-tok, .step-dur, .step-st { color: var(--t-text-muted, #6b7280); }
.step-st[data-status="error"] { color: var(--err); }
.step-dur { margin-left: auto; }
.step-body { margin: 6px 0 0; padding: 6px 8px; background: var(--t-bg-soft, #f6f7f9);
  border-radius: 6px; font-size: 11.5px; white-space: pre-wrap; word-break: break-all;
  max-height: 220px; overflow-y: auto; }
.step-body.result { color: var(--t-text-secondary, #374151); }
.empty { color: var(--t-text-muted, #9ca3af); font-size: 12.5px; padding: 12px 4px; }
</style>

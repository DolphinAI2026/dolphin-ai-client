<!-- frontend/src/components/v2/DeployConfirmModal.vue -->
<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { ElDialog, ElButton } from 'element-plus'
import { applicationApi } from '@/api/application'

const props = defineProps<{
  modelValue: boolean
  appName: string
  appCode: string
  changes: { kind: '+' | '~' | '-'; what: string }[]
  impacts: { affectedUsers: number; addedFlows: number; needMigration: boolean; etaMinutes: number }
  // Plan C (2026-05-19): 接 ai_chat artifact 部署 — 传 artifactId 走真接口
  // 不传则保留老 fallback (2.5s 假动画) — 用于 ChatPage.vue 等老 callsite
  sessionId?: number
  artifactId?: number
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm', env: 'dev' | 'test' | 'prod'): void
  (e: 'success', appId: number): void
  (e: 'failure', err: string): void
}>()

const ENVS = [
  { id: 'dev', label: '开发', tone: 'outline' },
  { id: 'test', label: '测试', tone: 'sky', isDefault: true },
  { id: 'prod', label: '生产', tone: 'rose' },
] as const

// 2026-05-19 image #30: 用户拍板"每个租户对应唯一 1 个低代码租户"，不需要选 env。
// 直接走 tenant 绑定的 default env (后端 deploy-from-artifact 在 env 未传时自走默认)。
const env = ref<'dev' | 'test' | 'prod'>('test')
const confirmCode = ref('')
const phase = ref<'pickEnv' | 'confirm' | 'running' | 'success' | 'failed'>('confirm')
const errorMsg = ref<string>('')
const deployedAppId = ref<number | null>(null)
const progressPct = ref<number>(0)

// polling state — 用于取消
let pollTimer: number | null = null
let cancelled = false

function clearPoll() {
  if (pollTimer != null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

// Reset state when the dialog re-opens.
watch(
  () => props.modelValue,
  v => {
    if (v) {
      phase.value = 'confirm'   // 直接进 confirm，跳过 pickEnv（image #30）
      env.value = 'test'
      confirmCode.value = ''
      errorMsg.value = ''
      deployedAppId.value = null
      progressPct.value = 0
      cancelled = false
    } else {
      // 关闭 modal 取消轮询
      cancelled = true
      clearPoll()
    }
  },
)

onBeforeUnmount(() => {
  cancelled = true
  clearPoll()
})

const isProd = computed(() => env.value === 'prod')
const canConfirm = computed(() => !isProd.value || confirmCode.value === props.appCode)

async function go() {
  if (phase.value === 'confirm' && canConfirm.value) {
    phase.value = 'running'
    errorMsg.value = ''
    progressPct.value = 5
    emit('confirm', env.value)

    // 真接口：传了 artifactId 才走 — 否则 fallback 老 2.5s 假动画
    if (props.artifactId) {
      await runRealDeploy()
    } else {
      // Legacy fallback (ChatPage.vue 等未升级 callsite)
      setTimeout(() => {
        if (cancelled) return
        phase.value = 'success'
      }, 2500)
    }
  }
}

async function runRealDeploy() {
  try {
    const resp = await applicationApi.deployFromArtifact({
      artifact_id: props.artifactId!,
      env: env.value,
    })
    deployedAppId.value = resp.app_id
    progressPct.value = 15
    // 进入轮询
    startPolling(resp.task_id, resp.app_id)
  } catch (e: any) {
    if (cancelled) return
    const msg = e?.response?.data?.detail || e?.message || '部署请求失败'
    errorMsg.value = msg
    phase.value = 'failed'
    emit('failure', msg)
  }
}

async function startPolling(taskId: string, appId: number) {
  let attempts = 0
  const maxAttempts = 60 // ~120s @ 2s 间隔
  const tick = async () => {
    if (cancelled) return
    attempts++
    try {
      const status = await applicationApi.getDeployStatus(taskId)
      // 进度推进（粗略）
      if (typeof status.progress === 'number') {
        progressPct.value = Math.max(progressPct.value, status.progress)
      }
      if (status.done) {
        if (status.error) {
          errorMsg.value = status.error
          phase.value = 'failed'
          emit('failure', status.error)
        } else {
          progressPct.value = 100
          phase.value = 'success'
          emit('success', appId)
        }
        return
      }
    } catch (e: any) {
      // 网络抖动单次失败 — 继续轮询；总超时控制由 maxAttempts 兜底
      console.warn('[DeployConfirmModal] poll error', e)
    }
    if (attempts >= maxAttempts) {
      if (cancelled) return
      // 超时不当失败 — 提示用户去应用详情页看进度
      errorMsg.value = '部署仍在进行中，请到「应用」列表查看详细进度'
      phase.value = 'failed'
      emit('failure', errorMsg.value)
      return
    }
    pollTimer = window.setTimeout(tick, 2000) as unknown as number
  }
  pollTimer = window.setTimeout(tick, 1500) as unknown as number
}

function close() {
  cancelled = true
  clearPoll()
  emit('update:modelValue', false)
}

function backToConfirm() {
  // 失败后允许返回上一步 (用户可改 env 或重试)
  phase.value = 'confirm'
  errorMsg.value = ''
  progressPct.value = 0
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="(v: any) => emit('update:modelValue', v)"
    width="640px"
    :show-close="phase !== 'running'"
    :title="phase === 'success' ? '部署成功' : phase === 'failed' ? '部署失败' : '部署到平台'"
  >
    <div v-if="phase === 'pickEnv'" class="dep">
      <div class="dep-section-title">1 · 选择目标环境</div>
      <div class="env-row">
        <button
          v-for="e in ENVS"
          :key="e.id"
          class="env-card"
          :class="['tone-' + e.tone, { active: env === e.id }]"
          @click="env = e.id"
        >
          <div class="env-name">{{ e.label }}</div>
          <div v-if="e.isDefault" class="env-default">默认</div>
        </button>
      </div>
      <div v-if="isProd" class="warn-bar">⚠️ 生产环境部署不可逆，提交前需输入应用编码确认</div>
    </div>

    <div v-else-if="phase === 'confirm'" class="dep">
      <div class="dep-section-title">1 · 变更预览</div>
      <ul v-if="changes.length" class="diff">
        <li v-for="c in changes" :key="c.what" :class="'diff-' + c.kind">
          <span class="diff-kind">{{ c.kind }}</span>
          <span class="diff-what">{{ c.what }}</span>
        </li>
      </ul>
      <div v-else class="diff-empty">未检测到模型/表单/流程层面的差异（首次部署或纯前端调整）</div>

      <div class="dep-section-title">2 · 影响范围</div>
      <div class="impact-row">
        <div class="impact-card">
          <div class="impact-num">{{ impacts.affectedUsers }}</div>
          <div class="impact-lbl">用户受影响</div>
        </div>
        <div class="impact-card">
          <div class="impact-num">{{ impacts.addedFlows }}</div>
          <div class="impact-lbl">流程新增</div>
        </div>
        <div class="impact-card">
          <div class="impact-num">{{ impacts.needMigration ? '是' : '否' }}</div>
          <div class="impact-lbl">数据迁移</div>
        </div>
        <div class="impact-card">
          <div class="impact-num">{{ impacts.etaMinutes }}m</div>
          <div class="impact-lbl">预计耗时</div>
        </div>
      </div>

      <div v-if="isProd" class="prod-confirm">
        <label>
          输入应用编码 <code>{{ appCode }}</code> 以确认：
        </label>
        <input v-model="confirmCode" class="input" :placeholder="appCode" />
      </div>
      <div class="safety">✓ 部署前自动备份 · 失败可一键回滚</div>
    </div>

    <div v-else-if="phase === 'running'" class="dep dep-center">
      <div class="loader" />
      <div>正在部署到 <b>{{ env }}</b>...</div>
      <div v-if="progressPct > 0" class="progress-wrap">
        <div class="progress-bar"><div class="progress-fill" :style="{ width: progressPct + '%' }" /></div>
        <div class="progress-text">{{ progressPct }}%</div>
      </div>
    </div>

    <div v-else-if="phase === 'failed'" class="dep dep-center">
      <div class="fail-mark">!</div>
      <div class="fail-title">部署到 <b>{{ env }}</b> 失败</div>
      <div v-if="errorMsg" class="fail-msg">{{ errorMsg }}</div>
    </div>

    <div v-else class="dep dep-center">
      <div class="success-mark">✓</div>
      <div>已部署到 <b>{{ env }}</b></div>
      <div v-if="appName" class="success-app">{{ appName }}</div>
      <div v-if="deployedAppId" class="success-app">应用 ID: {{ deployedAppId }}</div>
    </div>

    <template #footer>
      <div class="dep-foot">
        <el-button v-if="phase !== 'running'" @click="close">
          {{ phase === 'success' ? '关闭' : phase === 'failed' ? '关闭' : '取消' }}
        </el-button>
        <el-button v-if="phase === 'pickEnv'" type="primary" @click="go">下一步</el-button>
        <el-button v-else-if="phase === 'confirm'" type="primary" :disabled="!canConfirm" @click="go">
          {{ isProd ? '确认部署到生产' : '确认部署' }}
        </el-button>
        <el-button v-else-if="phase === 'failed'" type="primary" @click="backToConfirm">返回上一步</el-button>
        <el-button v-else-if="phase === 'success'" type="primary" @click="close">完成</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.dep { display: flex; flex-direction: column; gap: 14px; font-size: 13px; color: var(--text); }
.dep-section-title { font-size: 12px; font-weight: 600; letter-spacing: 0.04em; color: var(--text-3); text-transform: uppercase; }

.env-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.env-card { padding: 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; text-align: left; font-family: inherit; color: var(--text); transition: border-color 0.14s ease, box-shadow 0.14s ease; }
.env-card.active { border-color: currentColor; box-shadow: 0 0 0 3px var(--ring, var(--brand-ring)); }
.env-card.tone-outline.active { color: var(--text-2); --ring: rgba(0, 0, 0, 0.06); }
.env-card.tone-sky.active { color: var(--sky); --ring: var(--sky-bg); }
.env-card.tone-rose.active { color: var(--rose); --ring: var(--rose-bg); }
.env-name { font-size: 14px; font-weight: 600; }
.env-default { font-size: 11px; color: var(--text-3); margin-top: 2px; }

.warn-bar { padding: 10px 12px; border-radius: 8px; background: var(--rose-bg); color: var(--rose); font-size: 12.5px; }

.diff { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.diff li { display: flex; gap: 8px; align-items: center; padding: 6px 10px; border-radius: 6px; font-size: 12.5px; }
.diff-empty { padding: 8px 12px; border-radius: 6px; background: var(--surface-2); color: var(--text-3); font-size: 12.5px; }
.diff-\+ { background: var(--emerald-bg); color: var(--emerald); }
.diff-\~ { background: var(--amber-bg); color: var(--amber); }
.diff-\- { background: var(--rose-bg); color: var(--rose); }
.diff-kind { font-family: var(--d-font-mono); font-weight: 700; width: 14px; }

.impact-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.impact-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px; text-align: center; }
.impact-num { font-size: 18px; font-weight: 600; color: var(--text); }
.impact-lbl { font-size: 11px; color: var(--text-3); margin-top: 2px; }

.prod-confirm { display: flex; flex-direction: column; gap: 6px; }
.prod-confirm label { font-size: 12px; color: var(--text-2); }
.prod-confirm code { font-family: var(--d-font-mono); background: var(--code-bg); padding: 0 6px; border-radius: 4px; color: var(--code-text); }
.input { height: 34px; padding: 0 12px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); color: var(--text); font-size: 13px; outline: none; font-family: inherit; }
.input:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }

.safety { font-size: 12px; color: var(--emerald); padding-top: 4px; }

.dep-center { align-items: center; padding: 24px 0; gap: 14px; }
.loader { width: 36px; height: 36px; border: 3px solid var(--surface-3); border-top-color: var(--brand); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.success-mark { width: 48px; height: 48px; border-radius: 50%; background: var(--emerald-bg); color: var(--emerald); display: grid; place-items: center; font-size: 24px; font-weight: 600; }
.success-app { font-size: 12px; color: var(--text-3); }

.progress-wrap { display: flex; flex-direction: column; align-items: center; gap: 4px; width: 260px; }
.progress-bar { width: 100%; height: 6px; background: var(--surface-3); border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--brand); border-radius: 4px; transition: width 0.4s ease; }
.progress-text { font-size: 11px; color: var(--text-3); font-family: var(--d-font-mono); }

.fail-mark { width: 48px; height: 48px; border-radius: 50%; background: var(--rose-bg); color: var(--rose); display: grid; place-items: center; font-size: 24px; font-weight: 700; }
.fail-title { font-size: 13px; color: var(--text); }
.fail-msg { font-size: 12px; color: var(--rose); max-width: 480px; text-align: center; padding: 8px 12px; background: var(--rose-bg); border-radius: 6px; word-break: break-word; }

.dep-foot { display: flex; gap: 8px; justify-content: flex-end; }
</style>

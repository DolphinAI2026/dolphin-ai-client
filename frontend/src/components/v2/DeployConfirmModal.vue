<!-- frontend/src/components/v2/DeployConfirmModal.vue -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElDialog, ElButton } from 'element-plus'

const props = defineProps<{
  modelValue: boolean
  appName: string
  appCode: string
  changes: { kind: '+' | '~' | '-'; what: string }[]
  impacts: { affectedUsers: number; addedFlows: number; needMigration: boolean; etaMinutes: number }
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm', env: 'dev' | 'test' | 'prod'): void
}>()

const ENVS = [
  { id: 'dev', label: '开发', tone: 'outline' },
  { id: 'test', label: '测试', tone: 'sky', isDefault: true },
  { id: 'prod', label: '生产', tone: 'rose' },
] as const

const env = ref<'dev' | 'test' | 'prod'>('test')
const confirmCode = ref('')
const phase = ref<'pickEnv' | 'confirm' | 'running' | 'success'>('pickEnv')

// Reset state when the dialog re-opens.
watch(
  () => props.modelValue,
  v => {
    if (v) {
      phase.value = 'pickEnv'
      env.value = 'test'
      confirmCode.value = ''
    }
  },
)

const isProd = computed(() => env.value === 'prod')
const canConfirm = computed(() => !isProd.value || confirmCode.value === props.appCode)

function go() {
  if (phase.value === 'pickEnv') {
    phase.value = 'confirm'
  } else if (phase.value === 'confirm' && canConfirm.value) {
    phase.value = 'running'
    emit('confirm', env.value)
    // Simulated success — the parent's actual deploy flow already kicks off
    // when @confirm fires. This 2.5s timer is only the loader animation; if
    // the parent wants real progress, it can close + reopen the modal later.
    setTimeout(() => {
      phase.value = 'success'
    }, 2500)
  }
}

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="(v: any) => emit('update:modelValue', v)"
    width="640px"
    :show-close="phase !== 'running'"
    :title="phase === 'success' ? '部署成功' : '部署到平台'"
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
      <div class="dep-section-title">2 · 变更预览</div>
      <ul v-if="changes.length" class="diff">
        <li v-for="c in changes" :key="c.what" :class="'diff-' + c.kind">
          <span class="diff-kind">{{ c.kind }}</span>
          <span class="diff-what">{{ c.what }}</span>
        </li>
      </ul>
      <div v-else class="diff-empty">未检测到模型/表单/流程层面的差异（首次部署或纯前端调整）</div>

      <div class="dep-section-title">3 · 影响范围</div>
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
    </div>

    <div v-else class="dep dep-center">
      <div class="success-mark">✓</div>
      <div>已部署到 <b>{{ env }}</b></div>
      <div v-if="appName" class="success-app">{{ appName }}</div>
    </div>

    <template #footer>
      <div class="dep-foot">
        <el-button v-if="phase !== 'running'" @click="close">
          {{ phase === 'success' ? '关闭' : '取消' }}
        </el-button>
        <el-button v-if="phase === 'pickEnv'" type="primary" @click="go">下一步</el-button>
        <el-button v-else-if="phase === 'confirm'" type="primary" :disabled="!canConfirm" @click="go">
          {{ isProd ? '确认部署到生产' : '确认部署' }}
        </el-button>
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

.dep-foot { display: flex; gap: 8px; justify-content: flex-end; }
</style>

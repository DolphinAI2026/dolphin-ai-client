<template>
  <div class="gen-page">
    <nav class="nav-bar">
      <div class="nav-left">
        <button class="back-btn" @click="router.push('/chat')"><el-icon><ArrowLeft /></el-icon></button>
        <span class="title">{{ appName }}</span>
        <span class="title-badge" v-if="apaasAppId">已关联平台</span>
      </div>
      <div class="nav-right">
        <button class="nav-link" @click="router.push('/chat')">返回对话</button>
        <button v-if="apaasAppId" class="nav-link primary" @click="router.push('/apps')">查看应用</button>
      </div>
    </nav>

    <div class="gen-body">
      <div class="gen-inner">
        <!-- 顶部卡片 -->
        <div class="header-card">
          <div class="header-top">
            <div>
              <h2 class="header-title">部署到平台</h2>
              <p class="header-desc">逐步将配置部署到得帆云，每一步可独立验证</p>
            </div>
            <button class="run-all-btn" :disabled="executingStep !== null || allDone" @click="runAll">
              {{ allDone ? '✓ 全部完成' : '▶ 一键执行' }}
            </button>
          </div>
          <div class="progress-track"><div class="progress-fill" :style="{ width: progressPercent + '%' }"></div></div>
          <div class="progress-meta">
            <span>{{ completedCount }} / {{ steps.length }} 步完成</span>
            <span v-if="executingStep" class="exec-hint">正在执行...</span>
          </div>
        </div>

        <!-- 分组时间线 -->
        <div class="groups">
          <template v-for="(group, gi) in stepGroups" :key="gi">
            <div class="group" :class="{ 'group-done': group.allDone, 'group-error': group.hasError }">
              <div class="group-hd">
                <span class="group-icon">{{ group.icon }}</span>
                <span class="group-name">{{ group.title }}</span>
                <span v-if="group.allDone" class="group-badge done">完成</span>
                <span v-else-if="group.hasError" class="group-badge error">失败</span>
                <span v-else class="group-badge pending">{{ group.doneCount }}/{{ group.steps.length }}</span>
              </div>
              <div class="step-list">
                <div v-for="s in group.steps" :key="s.key" class="step" :class="[s.status, { running: executingStep === s.key }]">
                  <div class="dot-col">
                    <div class="dot" :class="[s.status, { pulse: executingStep === s.key }]">
                      <template v-if="s.status === 'completed'">✓</template>
                      <template v-else-if="s.status === 'error'">!</template>
                    </div>
                  </div>
                  <div class="step-body">
                    <div class="step-name">{{ s.label.replace(/^创建(模型|表单): /, '') }}</div>
                    <div v-if="s.result?.message" class="step-detail">{{ s.result.message }}</div>
                    <div v-if="s.error" class="step-err">{{ s.error }}</div>
                  </div>
                  <div class="step-act">
                    <template v-if="executingStep === s.key">
                      <span class="spinner"></span>
                    </template>
                    <template v-else-if="s.status === 'completed'">
                      <button class="act-btn redo" @click="resetAndExecute(s.key)" title="重新执行">↻</button>
                    </template>
                    <template v-else-if="s.status === 'error'">
                      <button class="act-btn retry" @click="executeOne(s.key)">重试</button>
                    </template>
                    <template v-else-if="s.deps_met">
                      <button class="act-btn run" @click="executeOne(s.key)">执行</button>
                    </template>
                    <template v-else>
                      <span class="lock">🔒</span>
                    </template>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- 完成 -->
        <div v-if="allDone" class="done-card">
          <div class="done-emoji">🎉</div>
          <div class="done-info">
            <h3>部署完成</h3>
            <p>所有 {{ steps.length }} 个步骤已成功执行</p>
          </div>
          <button class="done-btn" @click="router.push('/apps')">查看应用 →</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElIcon, ElMessage } from 'element-plus'
import { applicationApi } from '@/api/application'

interface Step { key: string; label: string; status: 'pending' | 'completed' | 'error'; deps_met: boolean; model_index?: number; error?: string; result?: Record<string, any> }

const router = useRouter()
const route = useRoute()
const appName = ref('')
const apaasAppId = ref('')
const steps = ref<Step[]>([])
const executingStep = ref<string | null>(null)

const appId = computed(() => Number(route.params.id))
const completedCount = computed(() => steps.value.filter(s => s.status === 'completed').length)
const progressPercent = computed(() => steps.value.length ? Math.round(completedCount.value / steps.value.length * 100) : 0)
const allDone = computed(() => steps.value.length > 0 && completedCount.value === steps.value.length)

// 分组
const stepGroups = computed(() => {
  const groups = [
    { title: '初始化', icon: '🚀', keys: (s: Step) => s.key === 'create_app' },
    { title: '公共资源', icon: '📦', keys: (s: Step) => s.key === 'create_roles_dicts' },
    { title: '数据模型', icon: '🗃', keys: (s: Step) => s.key.startsWith('create_model:') },
    { title: '表单配置', icon: '📋', keys: (s: Step) => s.key.startsWith('create_form:') },
    { title: '权限配置', icon: '🔐', keys: (s: Step) => s.key === 'configure_permissions' },
  ]
  return groups.map(g => {
    const ss = steps.value.filter(g.keys)
    return {
      ...g,
      steps: ss,
      allDone: ss.length > 0 && ss.every(s => s.status === 'completed'),
      hasError: ss.some(s => s.status === 'error'),
      doneCount: ss.filter(s => s.status === 'completed').length,
    }
  }).filter(g => g.steps.length > 0)
})

async function loadStatus() {
  try {
    const resp = await applicationApi.getStepStatus(appId.value)
    steps.value = resp.steps || []
    apaasAppId.value = resp.apaas_app_id || ''
  } catch { ElMessage.error('加载失败') }
}

async function executeOne(stepKey: string) {
  executingStep.value = stepKey
  try {
    const resp = await applicationApi.executeStep(appId.value, stepKey)
    if (resp.status === 'error') ElMessage.error(resp.error || '失败')
  } catch (e: any) { ElMessage.error(e.message || '失败') }
  finally { executingStep.value = null; await loadStatus() }
}

async function resetAndExecute(stepKey: string) {
  await applicationApi.resetStep(appId.value, stepKey)
  await loadStatus()
  await executeOne(stepKey)
}

async function runAll() {
  for (const s of steps.value) {
    if (s.status === 'completed') continue
    await loadStatus()
    const fresh = steps.value.find(x => x.key === s.key)
    if (!fresh || !fresh.deps_met) continue
    executingStep.value = s.key
    const resp = await applicationApi.executeStep(appId.value, s.key)
    await loadStatus()
    if (resp.status === 'error') { ElMessage.error(resp.error + '，已暂停'); executingStep.value = null; return }
  }
  executingStep.value = null
  ElMessage.success('全部完成！')
}

onMounted(async () => {
  if (!appId.value) return
  try { const app = await applicationApi.get(appId.value) as any; appName.value = app.app_name || ''; await loadStatus() }
  catch { ElMessage.error('加载失败') }
})
</script>

<style scoped>
.gen-page { height: 100vh; display: flex; flex-direction: column; background: #f8f9fb; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }

/* 导航 */
.nav-bar { display: flex; justify-content: space-between; align-items: center; padding: 0 24px; height: 52px; background: #fff; border-bottom: 1px solid #eee; flex-shrink: 0; }
.nav-left { display: flex; align-items: center; gap: 10px; }
.back-btn { all: unset; cursor: pointer; color: #999; padding: 4px; display: flex; }
.back-btn:hover { color: #333; }
.title { font-size: 15px; font-weight: 600; color: #111; }
.title-badge { font-size: 10px; padding: 2px 8px; background: #e8faf0; color: #0a8; border-radius: 99px; font-weight: 500; }
.nav-right { display: flex; gap: 8px; }
.nav-link { font-size: 13px; color: #666; background: #fff; border: 1px solid #ddd; cursor: pointer; padding: 6px 14px; border-radius: 8px; }
.nav-link:hover { border-color: #bbb; background: #fafafa; }
.nav-link.primary { background: #111; color: #fff; border-color: #111; }
.nav-link.primary:hover { background: #333; }

/* 内容 */
.gen-body { flex: 1; overflow-y: auto; }
.gen-inner { max-width: 600px; margin: 0 auto; padding: 28px 20px 60px; }

/* 顶部卡片 */
.header-card { background: #fff; border: 1px solid #eee; border-radius: 14px; padding: 22px; margin-bottom: 28px; }
.header-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.header-title { font-size: 17px; font-weight: 700; color: #111; margin: 0 0 4px; }
.header-desc { font-size: 12px; color: #aaa; margin: 0; }
.run-all-btn { padding: 9px 18px; background: #111; color: #fff; border: none; border-radius: 9px; font-size: 13px; cursor: pointer; font-weight: 500; }
.run-all-btn:hover:not(:disabled) { background: #333; }
.run-all-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.progress-track { height: 3px; background: #f0f0f0; border-radius: 2px; overflow: hidden; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #8b5cf6); border-radius: 2px; transition: width 0.5s ease; }
.progress-meta { display: flex; justify-content: space-between; margin-top: 8px; font-size: 11px; color: #bbb; }
.exec-hint { color: #6366f1; }

/* 分组 */
.groups { display: flex; flex-direction: column; gap: 10px; }
.group { background: #fff; border: 1px solid #eee; border-radius: 12px; overflow: hidden; }
.group-done { border-color: #c6f6d5; }
.group-error { border-color: #fed7d7; }
.group-hd { display: flex; align-items: center; gap: 8px; padding: 12px 18px; background: #fafbfc; }
.group-icon { font-size: 14px; }
.group-name { font-size: 13px; font-weight: 600; color: #444; flex: 1; }
.group-badge { font-size: 10px; padding: 2px 8px; border-radius: 99px; font-weight: 600; }
.group-badge.done { background: #e8faf0; color: #0a8; }
.group-badge.error { background: #fff0f0; color: #e53; }
.group-badge.pending { background: #f5f5f5; color: #999; }

/* 步骤 */
.step-list { padding: 2px 0; }
.step { display: flex; align-items: center; padding: 9px 18px; gap: 12px; }
.step + .step { border-top: 1px solid #f7f7f7; }
.step:hover { background: #fcfcfd; }

/* 圆点 */
.dot-col { width: 22px; display: flex; justify-content: center; flex-shrink: 0; }
.dot { width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; color: #fff; }
.dot.completed { background: #0a8; }
.dot.error { background: #e53; }
.dot.pending { background: #e0e0e0; width: 8px; height: 8px; }
.dot.pulse { background: #6366f1; animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.35); } 50% { box-shadow: 0 0 0 7px rgba(99,102,241,0); } }

/* 内容 */
.step-body { flex: 1; min-width: 0; }
.step-name { font-size: 13px; color: #333; font-weight: 500; }
.step.completed .step-name { color: #888; }
.step.pending .step-name { color: #bbb; }
.step-detail { font-size: 11px; color: #0a8; margin-top: 1px; }
.step-err { font-size: 11px; color: #e53; margin-top: 1px; }

/* 按钮 */
.step-act { flex-shrink: 0; }
.act-btn { border: none; cursor: pointer; border-radius: 6px; font-weight: 500; }
.act-btn.run { padding: 4px 12px; background: #6366f1; color: #fff; font-size: 12px; }
.act-btn.run:hover { background: #4f46e5; }
.act-btn.retry { padding: 4px 12px; background: #e53; color: #fff; font-size: 12px; }
.act-btn.retry:hover { background: #c00; }
.act-btn.redo { padding: 2px 6px; background: none; color: #ccc; font-size: 16px; }
.act-btn.redo:hover { color: #6366f1; background: #f0f0ff; }
.spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #e5e7eb; border-top-color: #6366f1; border-radius: 50%; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.lock { font-size: 12px; opacity: 0.25; }

/* 完成 */
.done-card { display: flex; align-items: center; gap: 16px; background: linear-gradient(135deg, #e8faf0, #f0fdf4); border: 1px solid #b2e8cc; border-radius: 14px; padding: 22px; margin-top: 20px; }
.done-emoji { font-size: 32px; }
.done-info { flex: 1; }
.done-info h3 { margin: 0; font-size: 15px; font-weight: 700; color: #065f46; }
.done-info p { margin: 3px 0 0; font-size: 12px; color: #0a8; }
.done-btn { padding: 9px 18px; background: #0a8; color: #fff; border: none; border-radius: 9px; font-size: 13px; font-weight: 500; cursor: pointer; white-space: nowrap; }
.done-btn:hover { background: #087; }
</style>

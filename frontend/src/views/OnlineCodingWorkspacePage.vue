<template>
  <BuilderFrame :breadcrumbs="[{ label: 'Vibe Coding' }]">
    <template #actions>
      <button class="oc-top-btn" type="button" title="返回工作区列表" @click="goWorkspaceList">
        <el-icon><ArrowLeft /></el-icon>
        <span>工作区</span>
      </button>
    </template>

    <main class="oc-page builder-page is-ide-view" :class="{ 'has-preview-panel': showPreviewPanel }">
      <div v-if="loading" class="oc-loading">加载 Vibe Coding 工作区...</div>

      <section v-else-if="!isRepoReady" class="oc-git-shell">
        <section class="oc-git-card">
          <div class="oc-panel-head">
            <div>
              <span class="oc-kicker">VIBE CODING</span>
              <strong>绑定 Git 仓库</strong>
              <span>当前阶段先完成仓库接入，导入成功后直接进入代码 IDE。</span>
            </div>
            <em class="oc-stage discovery">Git 接入</em>
          </div>

          <div class="oc-git-note">
            先把仓库读进工作区。Vibe Coding 的对话式全代码开发等沙箱执行链路稳定后再开放，避免现在这层半成品流程干扰验证。
          </div>

          <label class="oc-field">
            <span>Git 仓库地址</span>
            <input v-model="repoUrl" placeholder="https://github.com/org/repo.git" />
          </label>
          <label class="oc-field">
            <span>开发目标</span>
            <textarea
              v-model="taskInput"
              rows="4"
              placeholder="可选。写清楚这次打开 IDE 后要处理的代码任务。"
            ></textarea>
          </label>

          <div class="oc-auth-tabs">
            <button type="button" :class="{ active: authMode === 'public' }" @click="authMode = 'public'">公开仓库</button>
            <button type="button" :class="{ active: authMode === 'token' }" @click="authMode = 'token'">Token 授权</button>
          </div>

          <div v-if="authMode === 'token'" class="oc-token-grid">
            <label class="oc-field">
              <span>Git 用户名</span>
              <input v-model="gitUsername" placeholder="x-access-token" />
            </label>
            <label class="oc-field">
              <span>Git Token</span>
              <input v-model="gitToken" type="password" placeholder="GitHub / GitLab Token" />
            </label>
          </div>

          <div v-if="workspace?.import_error" class="oc-error">
            {{ workspace.import_error }}
          </div>

          <button class="oc-primary oc-repo-action" type="button" :disabled="submitting || !repoUrl.trim()" @click="submitWorkspace">
            <el-icon :class="{ spin: submitting }"><Refresh /></el-icon>
            <span>{{ submitting ? '导入中...' : workspace ? '重新导入并打开 IDE' : '导入仓库并打开 IDE' }}</span>
          </button>
        </section>
      </section>

      <template v-else>
        <section class="oc-ide-toolbar">
          <div class="oc-ide-context">
            <span class="oc-status-dot"></span>
            <strong>{{ workspaceTitle }}</strong>
            <span>{{ workspace?.branch || 'main' }}</span>
            <span v-if="workspace?.id">{{ workspace.id }}</span>
          </div>
          <div class="oc-ide-actions">
            <span v-if="showPreviewPanel || runtimeRunning || runtimeBusy" class="oc-runtime-pill" :class="runtimeStatusClass">
              {{ runtimeStatusLabel }}
            </span>
            <button
              v-if="showPreviewPanel || runtimeRunning || runtimeBusy"
              class="oc-secondary"
              type="button"
              :disabled="runtimeBusy"
              @click="refreshPreviewRuntimeStatus(true)"
            >
              <el-icon :class="{ spin: runtimeLogsLoading }"><Refresh /></el-icon>
              <span>运行状态</span>
            </button>
            <button
              v-if="!runtimeRunning"
              class="oc-secondary"
              type="button"
              :disabled="runtimeStartDisabled"
              @click="startPreviewRuntime"
            >
              <el-icon :class="{ spin: runtimeBusy }"><Monitor /></el-icon>
              <span>{{ runtimeBusy ? '启动中' : '实验预览' }}</span>
            </button>
            <button v-else class="oc-secondary danger" type="button" :disabled="runtimeBusy" @click="stopPreviewRuntime">
              <span>停止预览</span>
            </button>
            <button v-if="runtimePreviewUrl" class="oc-icon-btn" type="button" title="打开预览" @click="openPreviewWindow">
              <el-icon><TopRight /></el-icon>
            </button>
            <button class="oc-icon-btn" type="button" :disabled="openingIde" title="重新加载 IDE" @click="() => openIde(false)">
              <el-icon :class="{ spin: openingIde }"><Refresh /></el-icon>
            </button>
          </div>
        </section>

        <section v-if="showPreviewPanel" class="oc-runtime-panel" :class="{ 'has-detail': showRuntimeDetails }">
          <div class="oc-runtime-main">
            <div>
              <strong>实验预览</strong>
              <span>{{ runtimeSummary }}</span>
            </div>
            <a v-if="runtimePreviewUrl" :href="runtimePreviewUrl" target="_blank" rel="noreferrer">
              {{ runtimePreviewUrl }}
            </a>
          </div>
          <div v-if="showRuntimeDetails" class="oc-runtime-meta">
            <span>{{ runtimeWorkingDir }}</span>
            <span>{{ runtimeCommandText }}</span>
          </div>
          <pre v-if="previewLogs" class="oc-runtime-logs">{{ previewLogs }}</pre>
          <div v-if="runtimeError" class="oc-runtime-error">{{ runtimeError }}</div>
        </section>

        <section class="oc-ide-pane">
          <iframe
            v-if="ideUrl"
            :key="ideUrl"
            :src="ideUrl"
            class="oc-ide-frame"
            allow="clipboard-read; clipboard-write"
            @load="ideLoaded = true"
            @error="ideLoadError = 'Web IDE 加载失败'"
          ></iframe>
          <div v-if="!ideLoaded" class="oc-ide-loading">
            <strong>{{ ideLoadError || '正在加载 Web IDE...' }}</strong>
            <button v-if="ideLoadError" type="button" @click="() => openIde()">重新加载</button>
          </div>
        </section>
      </template>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  ChatDotRound,
  CircleCheck,
  Monitor,
  Refresh,
  TopRight,
} from '@element-plus/icons-vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import CodingStreamMessages from '@/components/coding/CodingStreamMessages.vue'
import {
  onlineCodingApi,
  type OnlineCodingWorkspace,
  type OnlinePreviewProject,
  type OnlinePreviewRuntime,
} from '@/api/onlineCoding'
import { useThemeStore } from '@/stores/theme'
import { useStreamMessages } from './coding/useStreamMessages'

type DevStage = 'discovery' | 'spec' | 'confirmed' | 'building' | 'ready'

const route = useRoute()
const router = useRouter()
const themeStore = useThemeStore()

const loading = ref(true)
const submitting = ref(false)
const openingIde = ref(false)
const agentBusy = ref(false)
const activeView = ref<'chat' | 'ide'>('chat')
const workspace = ref<OnlineCodingWorkspace | null>(null)
const repoUrl = ref('')
const taskInput = ref('')
const authMode = ref<'public' | 'token'>('public')
const gitUsername = ref('x-access-token')
const gitToken = ref('')
const agentInput = ref('')
const devStage = ref<DevStage>('discovery')
const specDraft = ref('')
const specConfirmed = ref(false)
const selectedFile = ref('')
const fileContent = ref('')
const fileLoading = ref(false)
const fileError = ref('')
const ideUrl = ref('')
const ideLoaded = ref(false)
const ideLoadError = ref('')
const previewProject = ref<OnlinePreviewProject | null>(null)
const previewRuntime = ref<OnlinePreviewRuntime | null>(null)
const previewLogs = ref('')
const runtimeBusy = ref(false)
const runtimeLogsLoading = ref(false)
const runtimeError = ref('')
const previewPanelOpen = ref(false)

const {
  streamMessages,
  addStreamMsg,
  addStepRunningMsg,
  completeStepMsg,
} = useStreamMessages()

const routeWorkspaceId = computed(() => {
  const raw = route.params.id
  const value = Array.isArray(raw) ? raw[0] : raw
  return value ? String(value) : ''
})

function routePromptText() {
  const raw = route.query.prompt
  const value = Array.isArray(raw) ? raw[0] : raw
  return value ? String(value) : ''
}

function isWorkspaceReady(current?: OnlineCodingWorkspace | null) {
  return !!current && current.status === 'repo_imported'
}

const isRepoReady = computed(() => isWorkspaceReady(workspace.value))
const workspaceFiles = computed(() => workspace.value?.files || [])
const isEmptyRepo = computed(() => isRepoReady.value && workspaceFiles.value.length === 0 && !(workspace.value?.file_count || 0))
const workspaceTitle = computed(() => repoName(workspace.value?.repo_url) || workspace.value?.id || 'Vibe Coding')
const stageLabel = computed(() => {
  if (devStage.value === 'discovery') return '需求澄清'
  if (devStage.value === 'spec') return 'SPEC 草稿'
  if (devStage.value === 'confirmed') return '等待构建'
  if (devStage.value === 'building') return '构建准备'
  return '可接管'
})
const stageCopy = computed(() => {
  if (devStage.value === 'discovery') return '先把想法整理成可执行 SPEC'
  if (devStage.value === 'spec') return 'SPEC 可编辑，确认后进入构建计划'
  if (devStage.value === 'confirmed') return '需求基线已确认，可以开始执行'
  if (devStage.value === 'building') return '正在拆解文件影响面和执行步骤'
  return '可继续对话，也可打开 IDE 查看代码'
})
const specStats = computed(() => {
  const chars = specDraft.value.trim().length
  if (!chars) return '尚未生成'
  const sections = (specDraft.value.match(/^##\s+/gm) || []).length
  return `${sections || 1} 个章节 · ${chars} 字`
})
const repoSummary = computed(() => {
  const files = workspaceFiles.value
  if (!workspace.value) return '未选择仓库'
  if (isEmptyRepo.value) return '空仓库；可从 0 到 1 初始化项目'
  const topDirs = summarizeCounts(files.map(file => file.includes('/') ? file.split('/')[0] || '/' : '/'), 3)
  const exts = summarizeCounts(files.map(file => {
    const name = file.split('/').pop() || file
    return name.includes('.') ? `.${name.split('.').pop()}` : 'no-ext'
  }), 3)
  return `${workspace.value.file_count || files.length} 个文件；${topDirs || '根目录'}；${exts || '暂无类型'}`
})
const runtimeRunning = computed(() => previewRuntime.value?.status === 'running')
const runtimePreviewUrl = computed(() => previewRuntime.value?.preview_url || '')
const runtimeStatusClass = computed(() => previewRuntime.value?.status || previewProject.value?.status || 'stopped')
const runtimeStatusLabel = computed(() => {
  const status = runtimeStatusClass.value
  const labels: Record<string, string> = {
    unsupported: '未识别项目',
    detected: '已识别',
    installing: '安装依赖中',
    starting: '启动中',
    running: '运行中',
    stopped: '未运行',
    error: '运行失败',
  }
  return labels[status] || '未检测'
})
const runtimeSummary = computed(() => {
  if (runtimeError.value) return runtimeError.value
  if (previewProject.value?.supported === false) return previewProject.value.reason || '当前仓库暂未识别到可预览的前端运行入口'
  if (runtimeRunning.value) return `端口 ${previewRuntime.value?.port} 已就绪，可在新窗口打开预览`
  if (runtimeBusy.value) return '正在准备依赖和启动开发服务，首次启动可能需要更久'
  return '按需检测仓库里的前端入口并启动实验预览服务'
})
const runtimeWorkingDir = computed(() => {
  const dir = previewRuntime.value?.working_dir || previewProject.value?.working_dir
  if (!dir) return '运行目录：待检测'
  return `运行目录：${shortPath(dir)}`
})
const runtimeCommandText = computed(() => {
  const command = previewRuntime.value?.command || previewProject.value?.start_command
  if (!command?.length) return '启动命令：待检测'
  return `启动命令：${command.join(' ')}`
})
const runtimeStartDisabled = computed(() => (
  runtimeBusy.value ||
  runtimeRunning.value ||
  !isRepoReady.value ||
  previewProject.value?.supported === false
))
const showPreviewPanel = computed(() => (
  previewPanelOpen.value ||
  runtimeRunning.value ||
  runtimeBusy.value ||
  Boolean(runtimePreviewUrl.value)
))
const showRuntimeDetails = computed(() => Boolean(runtimePreviewUrl.value || runtimeError.value || previewLogs.value))

onMounted(loadFromRoute)

watch(
  () => [route.params.id, route.query.view, route.query.prompt],
  () => {
    void loadFromRoute()
  },
)

async function loadFromRoute() {
  const id = routeWorkspaceId.value
  loading.value = true
  ideUrl.value = ''
  ideLoaded.value = false
  ideLoadError.value = ''
  try {
    if (!id) {
      const prompt = routePromptText()
      workspace.value = null
      repoUrl.value = ''
      taskInput.value = prompt
      specDraft.value = prompt ? buildSpecDraft(prompt) : ''
      specConfirmed.value = false
      devStage.value = prompt ? 'spec' : 'discovery'
      seedImportStream()
      return
    }

    const loaded = await onlineCodingApi.getWorkspace(id)
    workspace.value = loaded
    repoUrl.value = loaded.repo_url || ''
    taskInput.value = loaded.task || ''
    if (isWorkspaceReady(loaded)) {
      await prepareStudio()
      await openIde(false)
    } else {
      resetRuntimeState()
      seedImportStream(loaded)
    }
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || 'Vibe Coding 工作区加载失败')
    seedImportStream()
  } finally {
    loading.value = false
  }
}

function seedImportStream(current?: OnlineCodingWorkspace | null) {
  streamMessages.value = []
  addStreamMsg({
    type: 'message',
    content: [
      '这是 Vibe Coding 的独立工作台入口。先通过对话澄清需求并沉淀 SPEC，不急着打开 IDE。',
      '',
      current?.id
        ? '当前工作区还没有完成仓库导入。你可以继续补充需求；仓库地址和授权可以稍后再接入。'
        : taskInput.value
          ? '开发目标已经带入。我会先把它整理成 SPEC 草稿，仓库准备好以后再进入读码和构建。'
          : '直接描述你要构建的应用、页面、流程或问题。我会先做需求梳理和 SPEC，不会把你丢到仓库导入表单里。',
    ].join('\n'),
  })
  addStepRunningMsg('等待需求输入...', 'online_import_waiting')
}

async function ensurePlanningWorkspace(goal?: string) {
  if (workspace.value?.id) return workspace.value
  const task =
    taskInput.value.trim() ||
    goal?.trim() ||
    specDraft.value.split('\n').find(line => line.trim())?.replace(/^#\s*/, '').trim() ||
    '待澄清的 Vibe Coding 需求'
  const created = await onlineCodingApi.createWorkspace({ task })
  workspace.value = created
  taskInput.value = created.task || task
  if (!routeWorkspaceId.value) {
    await router.replace({ path: `/vibe-coding/workspaces/${created.id}` })
  }
  return created
}

async function submitWorkspace() {
  const payload = onlineAuthPayload()
  if (!payload.repo_url && !payload.task) {
    ElMessage.warning('请填写 Git 仓库地址或开发目标')
    return
  }
  submitting.value = true
  addStreamMsg({ type: 'user', content: summarizeSubmitPayload(payload) })
  completeStepMsg('online_import_waiting', '已接收导入配置')
  addStepRunningMsg(workspace.value ? '正在重新导入仓库...' : '正在创建 Vibe Coding 工作区...', 'online_importing')
  try {
    const result = workspace.value
      ? await onlineCodingApi.importWorkspace(workspace.value.id, payload)
      : await onlineCodingApi.createWorkspace(payload)
    workspace.value = result
    repoUrl.value = result.repo_url || repoUrl.value
    taskInput.value = result.task || taskInput.value
    if (isWorkspaceReady(result)) {
      const fileCount = result.file_count || result.files.length
      completeStepMsg('online_importing', fileCount > 0 ? `仓库已导入：${fileCount} 个文件` : '空仓库已接入')
      if (fileCount > 0) {
        addStreamMsg({
          type: 'tool',
          content: `扫描 ${repoName(result.repo_url) || result.id} 仓库文件`,
          result: fileListPreview(result.files),
          resultCollapsed: true,
        })
      } else {
        addStreamMsg({
          type: 'message',
          content: '这是一个空仓库，可以直接进入 IDE，让 AI 从 0 到 1 初始化项目结构和首版代码。',
        })
      }
      await router.replace({ path: `/vibe-coding/workspaces/${result.id}`, query: { view: 'ide' } })
      await prepareStudio()
      await openIde(false)
    } else if (result.status === 'import_failed') {
      completeStepMsg('online_importing', '仓库导入失败')
      addStreamMsg({ type: 'error', content: result.import_error || '仓库导入失败，请检查地址和访问权限。' })
      await router.replace({ path: `/vibe-coding/workspaces/${result.id}` })
    } else {
      completeStepMsg('online_importing', '工作区已创建')
      addStreamMsg({ type: 'message', content: '工作区已经创建。继续补充 Git 仓库地址后，可以导入代码并进入 AI 工作台。' })
      await router.replace({ path: `/vibe-coding/workspaces/${result.id}` })
    }
  } catch (error: any) {
    addStreamMsg({ type: 'error', content: error?.response?.data?.detail || error?.message || 'Vibe Coding 工作区创建失败' })
  } finally {
    submitting.value = false
  }
}

async function prepareStudio() {
  const current = workspace.value
  if (!current) return
  activeView.value = 'ide'
  specConfirmed.value = Boolean(current.spec_confirmed)
  specDraft.value = current.spec_draft || buildSpecDraft(current.task || '待补充开发目标')
  devStage.value = specConfirmed.value ? 'confirmed' : current.task ? 'spec' : 'discovery'
  streamMessages.value = []
  addStreamMsg({
    type: 'message',
    content: [
      summarizeRepo(),
      '',
      isEmptyRepo.value
        ? '你可以在对话里继续补充技术栈、页面范围、数据模型和验收标准；也可以直接进入 IDE 初始化首版工程。'
        : '我们先不急着打开 IDE。你可以继续补充系统目标、角色、流程、字段和验收标准；右侧 SPEC 会保存到当前工作区。',
    ].join('\n'),
  })
  if (current.files.length > 0) {
    addStreamMsg({
      type: 'tool',
      content: `扫描 ${workspaceTitle.value} 的仓库文件`,
      result: fileListPreview(current.files),
      resultCollapsed: true,
    })
  }
  addStepRunningMsg('等待用户描述开发目标...', 'online_wait_goal')
  const first = preferredFile(current.files)
  if (first) {
    await selectFile(first)
  }
}

async function sendAgentMessage() {
  const raw = agentInput.value.trim()
  if (!raw || agentBusy.value) return
  agentInput.value = ''
  agentBusy.value = true
  addStreamMsg({ type: 'user', content: raw })
  completeStepMsg('online_wait_goal', '收到开发目标')
  completeStepMsg('online_import_waiting', '收到需求输入')
  try {
    await ensurePlanningWorkspace(raw)
    mergeSpec(raw)
    if (!taskInput.value.trim() || taskInput.value === '导入仓库后补充开发任务') {
      taskInput.value = raw
    }
    specConfirmed.value = false
    devStage.value = 'spec'
    addStreamMsg({
      type: 'thinking',
      content: [
        '我先把这轮描述当作需求输入处理，不用关键词去猜“确认”或“构建”。',
        isRepoReady.value
          ? '处理顺序是：合并 SPEC、读取仓库上下文、输出影响面，然后等用户显式确认。'
          : '处理顺序是：合并 SPEC、补齐业务问题、等需求确认；仓库和 IDE 等到需要读码时再接入。',
      ].join('\n'),
    })
    streamStep('开发 SPEC 已更新')
    if (isRepoReady.value) {
      addStreamMsg({
        type: 'tool',
        content: `扫描 ${workspaceTitle.value} 工作区文件`,
        result: fileListPreview(workspaceFiles.value, 32),
        resultCollapsed: true,
      })
      const analysis = await buildWorkspaceAnalysis(raw)
      addStreamMsg({
        type: 'tool',
        content: '读取关键文件并生成项目摘要',
        result: analysis,
        resultCollapsed: false,
      })
    } else {
      addStreamMsg({
        type: 'tool',
        content: '整理需求为 SPEC 草稿',
        result: specDraft.value,
        resultCollapsed: true,
      })
    }
    await persistSpec(false)
    addStreamMsg({
      type: 'message',
      content: isRepoReady.value
        ? '我已经把这轮输入合入右侧 SPEC 草稿，并保存到当前工作区。你可以继续补充，也可以在右侧确认 SPEC 后开始构建。'
        : '我已经把这轮输入合入右侧 SPEC 草稿，并保存到当前工作区。你可以继续补充，仓库地址可以在右侧稍后接入。',
    })
  } catch (error: any) {
    addStreamMsg({ type: 'error', content: error?.message || '分析工作区失败，请稍后重试。' })
  } finally {
    agentBusy.value = false
  }
}

async function confirmSpec() {
  ensureSpec()
  if (specConfirmed.value) return
  try {
    await ensurePlanningWorkspace(specDraft.value)
  } catch (error: any) {
    ElMessage.warning(error?.response?.data?.detail || '工作区创建失败，SPEC 暂未保存')
    return
  }
  specConfirmed.value = true
  devStage.value = 'confirmed'
  await persistSpec(true)
  addStreamMsg({ type: 'user', content: '确认 SPEC' })
  streamStep('SPEC 已确认')
  addStreamMsg({
    type: 'message',
    content: 'SPEC 已确认。我会按这个需求基线进入构建计划：先读关键入口和配置，再定位影响文件，随后分批修改、运行构建/测试，并把过程逐步展示出来。',
  })
}

async function startBuild() {
  ensureSpec()
  if (!specConfirmed.value) {
    await confirmSpec()
  }
  if (!isRepoReady.value) {
    addStreamMsg({ type: 'user', content: '开始构建' })
    addStreamMsg({
      type: 'message',
      content: 'SPEC 已经确认。进入真实代码构建前，需要先在右侧连接仓库；仓库导入后我会读取代码、定位影响面，再进入文件修改、命令执行和测试反馈。',
    })
    ElMessage.info('先连接代码仓库，再进入构建执行')
    return
  }
  devStage.value = 'building'
  addStreamMsg({ type: 'user', content: '开始构建' })
  addStreamMsg({
    type: 'thinking',
    content: [
      '构建前先锁定边界：以右侧 SPEC 为准。',
      '下一步需要根据真实入口文件形成影响面，再进入文件修改和命令执行。',
    ].join('\n'),
  })
  streamStep('读取仓库上下文')
  const analysis = await buildWorkspaceAnalysis('开始构建')
  addStreamMsg({
    type: 'tool',
    content: '读取关键文件并生成构建计划',
    result: analysis,
    resultCollapsed: false,
  })
  addStreamMsg({
    type: 'message',
    content: [
      '当前已进入构建准备阶段。',
      '',
      '当前版本先把 SPEC、读码摘要和构建计划固定下来。接入 Online 执行器后，文件修改、命令执行、测试反馈和预览结果会继续复用这条流式过程展示。',
    ].join('\n'),
  })
  devStage.value = 'ready'
}

async function openIde(syncRoute = true) {
  const current = workspace.value
  if (!current || !isWorkspaceReady(current)) {
    ElMessage.info('仓库导入成功后才能打开 IDE')
    return
  }
  openingIde.value = true
  ideLoaded.value = false
  ideLoadError.value = ''
  try {
    const result = await onlineCodingApi.getIdeUrl(current.id, themeStore.mode)
    ideUrl.value = result.ide_url
    activeView.value = 'ide'
    if (syncRoute) {
      await router.replace({ path: `/vibe-coding/workspaces/${current.id}`, query: { view: 'ide' } })
    }
  } catch (error: any) {
    ElMessage.warning(error?.response?.data?.detail || error?.message || 'Web IDE 打开失败')
  } finally {
    openingIde.value = false
  }
}

function resetRuntimeState() {
  previewProject.value = null
  previewRuntime.value = null
  previewLogs.value = ''
  runtimeError.value = ''
  previewPanelOpen.value = false
}

async function refreshPreviewRuntimeStatus(showToast = false) {
  const current = workspace.value
  if (!current || !isWorkspaceReady(current)) return
  previewPanelOpen.value = true
  runtimeLogsLoading.value = true
  try {
    const [project, runtime] = await Promise.all([
      onlineCodingApi.detectPreviewRuntime(current.id).catch(() => null),
      onlineCodingApi.getPreviewRuntimeStatus(current.id),
    ])
    if (project) previewProject.value = project
    previewRuntime.value = runtime
    runtimeError.value = runtime.error || ''
    if (runtime.status === 'running') {
      await refreshPreviewRuntimeLogs()
    }
    if (showToast) ElMessage.success('预览运行状态已刷新')
  } catch (error: any) {
    runtimeError.value = error?.response?.data?.detail || error?.message || '预览运行状态读取失败'
    if (showToast) ElMessage.warning(runtimeError.value)
  } finally {
    runtimeLogsLoading.value = false
  }
}

async function startPreviewRuntime() {
  const current = workspace.value
  if (!current || !isWorkspaceReady(current) || runtimeBusy.value) return
  previewPanelOpen.value = true
  runtimeBusy.value = true
  runtimeError.value = ''
  previewLogs.value = ''
  try {
    const result = await onlineCodingApi.startPreviewRuntime(current.id)
    previewProject.value = result.project
    previewRuntime.value = result.runtime
    runtimeError.value = result.runtime.error || ''
    await refreshPreviewRuntimeLogs()
    if (result.runtime.status === 'running') {
      ElMessage.success('实验预览已启动')
    } else if (result.runtime.error) {
      ElMessage.warning(result.runtime.error)
    }
  } catch (error: any) {
    runtimeError.value = error?.response?.data?.detail || error?.message || '实验预览启动失败'
    ElMessage.error(runtimeError.value)
    await refreshPreviewRuntimeLogs()
  } finally {
    runtimeBusy.value = false
  }
}

async function stopPreviewRuntime() {
  const current = workspace.value
  if (!current || runtimeBusy.value) return
  previewPanelOpen.value = true
  runtimeBusy.value = true
  try {
    previewRuntime.value = await onlineCodingApi.stopPreviewRuntime(current.id)
    runtimeError.value = previewRuntime.value.error || ''
    await refreshPreviewRuntimeLogs()
    ElMessage.success('实验预览已停止')
  } catch (error: any) {
    runtimeError.value = error?.response?.data?.detail || error?.message || '实验预览停止失败'
    ElMessage.warning(runtimeError.value)
  } finally {
    runtimeBusy.value = false
  }
}

async function refreshPreviewRuntimeLogs() {
  const current = workspace.value
  if (!current?.id) return
  try {
    const result = await onlineCodingApi.getPreviewRuntimeLogs(current.id)
    previewLogs.value = result.logs.trim()
  } catch {
    previewLogs.value = ''
  }
}

function openPreviewWindow() {
  if (!runtimePreviewUrl.value) return
  window.open(runtimePreviewUrl.value, '_blank', 'noopener,noreferrer')
}

async function backToChat() {
  activeView.value = 'chat'
  if (workspace.value?.id) {
    await router.replace({ path: `/vibe-coding/workspaces/${workspace.value.id}` })
  }
}

async function selectFile(filePath: string) {
  const current = workspace.value
  if (!current || !filePath) return
  selectedFile.value = filePath
  fileLoading.value = true
  fileError.value = ''
  fileContent.value = ''
  try {
    const result = await onlineCodingApi.readFile(current.id, filePath)
    fileContent.value = result.content
  } catch (error: any) {
    fileError.value = error?.response?.data?.detail || '文件读取失败'
  } finally {
    fileLoading.value = false
  }
}

function onlineAuthPayload() {
  const payload: {
    repo_url?: string
    task?: string
    git_username?: string
    git_token?: string
  } = {}
  const repo = repoUrl.value.trim()
  const task = taskInput.value.trim()
  if (repo) payload.repo_url = repo
  if (task) payload.task = task
  if (authMode.value === 'token' && gitToken.value.trim()) {
    payload.git_username = gitUsername.value.trim() || 'x-access-token'
    payload.git_token = gitToken.value.trim()
  }
  return payload
}

function summarizeSubmitPayload(payload: { repo_url?: string; task?: string }) {
  return [
    payload.repo_url ? `仓库：${payload.repo_url}` : '',
    payload.task ? `目标：${payload.task}` : '',
  ].filter(Boolean).join('\n') || '创建 Vibe Coding 工作区'
}

function buildSpecDraft(goal: string) {
  const files = workspaceFiles.value
  const entryText = [
    'frontend/app/page.tsx',
    'frontend/src/main.ts',
    'frontend/src/App.vue',
    'app/page.tsx',
    'src/main.ts',
    'src/App.vue',
    'main.py',
    'app.py',
  ].filter(file => files.includes(file)).join('、') || '待进一步读码确认'
  return [
    `# ${goal || 'Vibe Coding 开发 SPEC'}`,
    '',
    '## 1. 目标',
    goal || '待和用户继续澄清。',
    '',
    '## 2. 待确认问题',
    '- 主要用户是谁？',
    '- 核心业务流程从哪里开始，到哪里结束？',
    '- 哪些页面或接口必须本轮完成？',
    '- 有哪些权限、异常、性能或兼容性约束？',
    '',
    '## 3. 当前仓库理解',
    `- 仓库：${workspaceTitle.value}`,
    `- 技术栈初判：${inferStack(files, new Map())}`,
    `- 可能入口：${entryText}`,
    '',
    '## 4. 用户与场景',
    '- 主要用户：待补充',
    '- 核心场景：待补充',
    '- 非目标：待补充',
    '',
    '## 5. 功能范围',
    '- 页面/模块：待补充',
    '- 数据模型：待补充',
    '- 接口/服务：待补充',
    '- 权限与状态：待补充',
    '',
    '## 6. 验收标准',
    '- 用户可以完成核心业务流程',
    '- 关键异常路径有明确提示',
    '- 构建、类型检查或项目现有测试可以通过',
    '',
    '## 7. 构建计划',
    '- 读取关键入口和配置文件',
    '- 定位影响文件',
    '- 分批修改并展示 diff',
    '- 运行构建/测试并修复错误',
    '- 生成预览和交付说明',
  ].join('\n')
}

function mergeSpec(message: string) {
  const current = specDraft.value.trim()
  if (!current) {
    specDraft.value = buildSpecDraft(message)
    return
  }
  specDraft.value = `${current}\n\n## 需求补充\n${message}`
}

function ensureSpec() {
  if (!specDraft.value.trim()) {
    specDraft.value = buildSpecDraft(taskInput.value.trim() || workspace.value?.task || '待补充开发目标')
  }
}

function markSpecDirty() {
  if (!specConfirmed.value) return
  specConfirmed.value = false
  devStage.value = 'spec'
}

async function persistSpec(confirmed = specConfirmed.value) {
  const current = workspace.value
  if (!current?.id) return
  try {
    const updated = await onlineCodingApi.updateSpec(current.id, {
      task: taskInput.value.trim() || current.task,
      spec_draft: specDraft.value,
      spec_confirmed: confirmed,
    })
    workspace.value = updated
  } catch (error: any) {
    ElMessage.warning(error?.response?.data?.detail || 'SPEC 保存失败，本地草稿仍保留')
  }
}

function summarizeRepo() {
  const current = workspace.value
  if (!current) return '仓库已经准备好，可以开始分析。'
  if (isEmptyRepo.value) {
    return `我已经接入 ${workspaceTitle.value}，这是一个空仓库。下一步可以直接描述产品目标，让 AI 初始化项目结构、README 和首版代码。`
  }
  return `我已经接入 ${workspaceTitle.value}，当前导入 ${current.file_count || current.files.length} 个文件。${repoSummary.value}。下一步可以让我分析架构、定位入口文件，或生成开发计划。`
}

async function buildWorkspaceAnalysis(userMessage: string) {
  const current = workspace.value
  if (!current) return '当前没有选中的 Vibe Coding 工作区。'
  const files = current.files || []
  if (files.length === 0) {
    return [
      userMessage ? '我检查了当前工作区状态。' : '',
      `项目：${workspaceTitle.value}，分支 ${current.branch || '未知'}，当前是空仓库。`,
      '这不是失败状态，适合作为 0-1 开发起点。',
      '下一步建议：先确定技术栈、项目目录、首屏功能和提交规范，然后在 IDE 中生成 README、项目脚手架和首版代码。',
    ].filter(Boolean).join('\n')
  }
  const targets = [selectedFile.value, ...pickAnalysisFiles(files)]
    .filter((file, index, arr): file is string => Boolean(file) && arr.indexOf(file) === index)
    .slice(0, 8)
  const loaded = await Promise.all(targets.map(async file => {
    try {
      const result = await onlineCodingApi.readFile(current.id, file)
      return { file, content: result.content }
    } catch {
      return { file, content: '' }
    }
  }))
  const contentByPath = new Map(loaded.filter(item => item.content).map(item => [item.file, item.content]))
  const entries = [
    'app/page.tsx',
    'pages/index.tsx',
    'src/main.ts',
    'src/main.js',
    'src/App.vue',
    'frontend/app/page.tsx',
    'frontend/src/main.ts',
    'main.py',
    'app.py',
    'backend/main.py',
  ].filter(file => files.includes(file))
  const packageSummaries = loaded
    .filter(item => /(^|\/)package\.json$/.test(item.file) && item.content)
    .map(item => extractPackageScripts(item.file, item.content))
    .filter(Boolean)
  return [
    userMessage ? '我按当前工作区文件做了一次快速读码。' : '',
    `项目：${workspaceTitle.value}，分支 ${current.branch || '未知'}，已导入 ${current.file_count || files.length} 个文件。`,
    `目录分布：${summarizeCounts(files.map(file => file.includes('/') ? file.split('/')[0] || '/' : '/')) || '暂无'}。`,
    `文件类型：${summarizeCounts(files.map(file => file.includes('.') ? `.${file.split('.').pop()}` : 'no-ext')) || '暂无'}。`,
    `技术栈判断：${inferStack(files, contentByPath)}。`,
    entries.length ? `疑似入口文件：${entries.slice(0, 5).join('、')}。` : '暂未发现典型入口文件，建议先看 README、package.json 和根目录配置。',
    packageSummaries.length ? `包脚本/依赖：${packageSummaries.join('；')}。` : '',
    `已读取关键文件：${loaded.filter(item => item.content).map(item => item.file).join('、') || '暂无可读关键文件'}。`,
    '下一步建议：先确认运行命令和入口页面，再定位本次需求影响的模块；进入修改阶段后接入沙箱执行器，按文件修改、命令、测试结果逐步展示。',
  ].filter(Boolean).join('\n')
}

function pickAnalysisFiles(files: string[]) {
  const preferred = [
    'README.md',
    'package.json',
    'frontend/package.json',
    'backend/package.json',
    'pyproject.toml',
    'requirements.txt',
    'backend/requirements.txt',
    'pom.xml',
    'go.mod',
    'vite.config.ts',
    'next.config.js',
    'next.config.ts',
    'src/main.ts',
    'src/App.vue',
    'app/page.tsx',
    'main.py',
    'app.py',
  ]
  const picks: string[] = []
  const add = (file?: string) => {
    if (file && files.includes(file) && !picks.includes(file)) picks.push(file)
  }
  preferred.forEach(add)
  for (const file of files) {
    if (picks.length >= 8) break
    if (/(^|\/)(package\.json|README\.md|pyproject\.toml|requirements\.txt|pom\.xml|go\.mod)$/i.test(file)) add(file)
  }
  return picks.slice(0, 8)
}

function inferStack(files: string[], contentByPath: Map<string, string>) {
  const corpus = `${files.join('\n')}\n${[...contentByPath.values()].join('\n')}`.toLowerCase()
  const stack: string[] = []
  if (corpus.includes('"next"') || files.some(file => file.startsWith('app/') || file.startsWith('pages/'))) stack.push('Next.js/React')
  else if (corpus.includes('"react"') || files.some(file => /\.(tsx|jsx)$/.test(file))) stack.push('React')
  if (corpus.includes('"vue"') || files.some(file => file.endsWith('.vue'))) stack.push('Vue')
  if (corpus.includes('"vite"') || files.some(file => file.startsWith('vite.config'))) stack.push('Vite')
  if (corpus.includes('tailwind') || files.some(file => /tailwind\.config\./.test(file))) stack.push('Tailwind CSS')
  if (files.some(file => file.endsWith('.py') || file.endsWith('/requirements.txt') || file === 'requirements.txt' || file === 'pyproject.toml')) stack.push('Python')
  if (files.some(file => file === 'pom.xml' || file.endsWith('.java'))) stack.push('Java/Maven')
  if (files.some(file => file === 'go.mod' || file.endsWith('.go'))) stack.push('Go')
  return stack.length ? stack.join('、') : '暂未从关键文件判断出明确技术栈'
}

function extractPackageScripts(pathName: string, content: string) {
  try {
    const pkg = JSON.parse(content)
    const scripts = pkg?.scripts && typeof pkg.scripts === 'object'
      ? Object.keys(pkg.scripts).slice(0, 6).join('、')
      : ''
    const deps = { ...(pkg?.dependencies || {}), ...(pkg?.devDependencies || {}) }
    const keyDeps = ['next', 'react', 'vue', 'vite', 'typescript', 'tailwindcss', 'playwright']
      .filter(dep => deps[dep])
      .slice(0, 6)
      .join('、')
    return `${pathName}${scripts ? ` scripts: ${scripts}` : ''}${keyDeps ? `；关键依赖: ${keyDeps}` : ''}`
  } catch {
    return ''
  }
}

function summarizeCounts(values: string[], limit = 5) {
  const counts = new Map<string, number>()
  for (const value of values) counts.set(value, (counts.get(value) || 0) + 1)
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([name, count]) => `${name}(${count})`)
    .join('、')
}

function fileListPreview(files: string[], limit = 48) {
  if (!files.length) return '当前工作区暂未返回文件列表。'
  const shown = files.slice(0, limit).join('\n')
  return files.length > limit ? `${shown}\n... 还有 ${files.length - limit} 个文件` : shown
}

function preferredFile(files: string[]) {
  const priority = ['README.md', 'package.json', 'pyproject.toml', 'pom.xml', 'src/main.ts', 'src/App.vue', 'app.py']
  return priority.find(file => files.includes(file)) || files.find(file => /readme/i.test(file)) || files[0] || ''
}

function streamStep(content: string) {
  addStreamMsg({
    type: 'status',
    content,
    stepDone: true,
    stepKey: `online_step_${Date.now()}`,
  })
}

function toggleStreamMessage(index: number) {
  const msg = streamMessages.value[index]
  if (msg) msg.collapsed = !msg.collapsed
}

function toggleStreamResult(index: number) {
  const msg = streamMessages.value[index]
  if (msg) msg.resultCollapsed = !msg.resultCollapsed
}

function repoName(repo?: string | null) {
  if (!repo) return ''
  const name = repo.trim().replace(/\/+$/, '').split('/').filter(Boolean).pop() || ''
  return name.replace(/\.git$/i, '')
}

function shortPath(pathName: string) {
  const repoIndex = pathName.lastIndexOf('/repo')
  if (repoIndex >= 0) return pathName.slice(repoIndex + 1)
  const parts = pathName.split('/').filter(Boolean)
  return parts.slice(-3).join('/') || pathName
}

function fileName(filePath: string) {
  return filePath.split('/').pop() || filePath
}

function goWorkspaceList() {
  router.push('/vibe-coding')
}
</script>

<style scoped>
.oc-page {
  min-height: calc(100vh - 64px);
  padding: 22px;
  background: #f6f8fc;
}

.oc-loading {
  color: #64748b;
  padding: 60px;
  text-align: center;
}

.oc-top-btn,
.oc-primary,
.oc-secondary,
.oc-mini,
.oc-icon-btn {
  border: 1px solid rgba(116, 128, 171, 0.18);
  border-radius: 10px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  font-weight: 740;
}

.oc-top-btn,
.oc-secondary,
.oc-mini {
  min-height: 36px;
  padding: 0 12px;
  background: #fff;
  color: #475569;
}

.oc-top-btn {
  min-height: 34px;
  padding: 0 10px;
  border-radius: 999px;
  background: transparent;
  box-shadow: none;
}

.oc-primary {
  min-height: 40px;
  padding: 0 15px;
  background: #151a25;
  border-color: #151a25;
  color: #fff;
}

.oc-primary:disabled,
.oc-secondary:disabled,
.oc-mini:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.oc-import-shell {
  width: min(1240px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(420px, 0.88fr) minmax(420px, 1fr);
  gap: 16px;
}

.oc-import-main,
.oc-import-side,
.oc-studio-header,
.oc-chat-panel,
.oc-spec-panel,
.oc-context-panel {
  border: 1px solid rgba(116, 128, 171, 0.16);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 48px rgba(38, 48, 84, 0.08);
}

.oc-import-main {
  padding: 24px;
}

.oc-kicker {
  display: block;
  color: #536dfe;
  font-size: 11px;
  font-weight: 820;
  letter-spacing: 0.08em;
}

.oc-import-main h1,
.oc-studio-header h1 {
  margin: 7px 0 0;
  color: #111827;
  font-size: 26px;
  line-height: 1.18;
}

.oc-import-main p,
.oc-studio-header p {
  margin: 9px 0 18px;
  color: #64748b;
  font-size: 14px;
  line-height: 1.65;
}

.oc-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 14px;
}

.oc-field span {
  color: #475569;
  font-size: 12px;
  font-weight: 760;
}

.oc-field input,
.oc-field textarea,
.oc-composer textarea,
.oc-spec-editor {
  width: 100%;
  border: 1px solid rgba(116, 128, 171, 0.18);
  border-radius: 12px;
  outline: none;
  background: #fff;
  color: #111827;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.55;
}

.oc-field input {
  height: 42px;
  padding: 0 12px;
}

.oc-field textarea,
.oc-composer textarea {
  resize: vertical;
  padding: 11px 12px;
}

.oc-field input:focus,
.oc-field textarea:focus,
.oc-composer textarea:focus,
.oc-spec-editor:focus {
  border-color: rgba(83, 109, 254, 0.45);
  box-shadow: 0 0 0 3px rgba(83, 109, 254, 0.10);
}

.oc-auth-tabs {
  margin: 16px 0 0;
  display: inline-flex;
  padding: 3px;
  border: 1px solid rgba(116, 128, 171, 0.16);
  border-radius: 11px;
  background: #f8fafc;
}

.oc-auth-tabs button {
  min-height: 30px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 760;
}

.oc-auth-tabs button.active {
  background: #fff;
  color: #1e293b;
  box-shadow: 0 1px 6px rgba(38, 48, 84, 0.08);
}

.oc-token-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.oc-error {
  margin: 14px 0;
  border-radius: 12px;
  border: 1px solid rgba(239, 68, 68, 0.18);
  background: rgba(254, 242, 242, 0.9);
  color: #b91c1c;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.5;
}

.oc-import-main > .oc-primary {
  width: 100%;
  margin-top: 18px;
}

.oc-import-side {
  min-height: 620px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.oc-git-shell {
  min-height: calc(100vh - 64px);
  display: grid;
  place-items: center;
  padding: 32px;
  background: #f6f8fc;
}

.oc-git-card {
  width: min(720px, 100%);
  border: 1px solid rgba(116, 128, 171, 0.16);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 18px 48px rgba(38, 48, 84, 0.08);
  padding: 20px;
}

.oc-git-note {
  margin: 16px 0 18px;
  border: 1px solid rgba(83, 109, 254, 0.14);
  border-radius: 12px;
  background: rgba(83, 109, 254, 0.06);
  color: #526179;
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.65;
}

.oc-planning-shell {
  width: min(1420px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(520px, 1fr) minmax(360px, 460px);
  gap: 16px;
  align-items: stretch;
}

.oc-plan-chat {
  min-height: calc(100vh - 128px);
}

.oc-plan-side {
  min-width: 0;
  display: grid;
  gap: 16px;
  align-content: start;
}

.oc-plan-card {
  min-width: 0;
  border: 1px solid rgba(116, 128, 171, 0.16);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 48px rgba(38, 48, 84, 0.08);
  overflow: hidden;
}

.oc-plan-card .oc-panel-head {
  min-height: 58px;
}

.oc-plan-spec-editor {
  min-height: 300px;
  border: 0;
  border-top: 1px solid rgba(116, 128, 171, 0.12);
  border-radius: 0;
  box-shadow: none !important;
}

.oc-soft-badge {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid rgba(116, 128, 171, 0.16);
  border-radius: 999px;
  background: #f8fafc;
  color: #64748b;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 760;
}

.oc-plan-card > .oc-field,
.oc-plan-card > .oc-auth-tabs,
.oc-plan-card > .oc-token-grid,
.oc-plan-card > .oc-error,
.oc-plan-card > .oc-repo-action {
  margin-left: 16px;
  margin-right: 16px;
}

.oc-repo-action {
  width: calc(100% - 32px);
  margin-top: 16px;
  margin-bottom: 16px;
}

.oc-page.is-ide-view {
  min-height: calc(100vh - 64px);
  padding: 0;
  background: #0d1117;
  overflow: hidden;
}

.oc-studio-header {
  width: min(1540px, 100%);
  margin: 0 auto 16px;
  padding: 17px 18px;
  display: flex;
  justify-content: space-between;
  gap: 18px;
}

.oc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.oc-meta span {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(116, 128, 171, 0.14);
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
  padding: 0 8px;
  font-size: 11px;
  font-weight: 720;
}

.oc-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

.oc-ide-toolbar {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: #0d1117;
  color: rgba(226, 232, 240, 0.88);
  padding: 0 16px;
}

.oc-ide-context,
.oc-ide-actions {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.oc-ide-context strong {
  max-width: min(36vw, 420px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(248, 250, 252, 0.94);
  font-size: 14px;
  font-weight: 780;
}

.oc-ide-context span:not(.oc-status-dot) {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.08);
  color: rgba(203, 213, 225, 0.72);
  padding: 0 8px;
  font-size: 11px;
  font-weight: 700;
}

.oc-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.14);
}

.oc-ide-toolbar .oc-secondary {
  min-height: 32px;
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.06);
  color: rgba(226, 232, 240, 0.86);
}

.oc-ide-toolbar .oc-secondary.danger {
  color: #fecaca;
}

.oc-icon-btn {
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: 9px;
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.06);
  color: rgba(226, 232, 240, 0.78);
}

.oc-icon-btn:hover:not(:disabled),
.oc-ide-toolbar .oc-secondary:hover {
  border-color: rgba(203, 213, 225, 0.28);
  background: rgba(255, 255, 255, 0.10);
  color: #fff;
}

.oc-secondary.active {
  border-color: rgba(83, 109, 254, 0.32);
  background: rgba(83, 109, 254, 0.08);
  color: #4357d4;
}

.oc-runtime-pill {
  min-height: 26px;
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.08);
  color: rgba(203, 213, 225, 0.76);
  padding: 0 9px;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 760;
}

.oc-runtime-pill.running {
  border-color: rgba(34, 197, 94, 0.26);
  background: rgba(34, 197, 94, 0.12);
  color: #86efac;
}

.oc-runtime-pill.installing,
.oc-runtime-pill.starting,
.oc-runtime-pill.detected {
  border-color: rgba(14, 165, 233, 0.26);
  background: rgba(14, 165, 233, 0.12);
  color: #7dd3fc;
}

.oc-runtime-pill.error,
.oc-runtime-pill.unsupported {
  border-color: rgba(248, 113, 113, 0.28);
  background: rgba(248, 113, 113, 0.12);
  color: #fecaca;
}

.oc-runtime-panel {
  min-height: 42px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: #0f141c;
  color: rgba(226, 232, 240, 0.82);
  padding: 7px 16px;
}

.oc-runtime-panel.has-detail {
  min-height: 56px;
}

.oc-runtime-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.oc-runtime-main strong {
  display: block;
  color: rgba(248, 250, 252, 0.94);
  font-size: 13px;
  line-height: 1.35;
}

.oc-runtime-main span,
.oc-runtime-main a,
.oc-runtime-meta span {
  font-size: 12px;
  line-height: 1.55;
}

.oc-runtime-main span {
  display: block;
  margin-top: 1px;
  color: rgba(203, 213, 225, 0.68);
}

.oc-runtime-main a {
  max-width: min(48vw, 720px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #93c5fd;
  text-decoration: none;
}

.oc-runtime-meta {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.oc-runtime-meta span {
  max-width: min(54vw, 760px);
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(148, 163, 184, 0.07);
  color: rgba(203, 213, 225, 0.72);
  padding: 0 8px;
}

.oc-runtime-logs {
  max-height: 92px;
  margin: 10px 0 0;
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 9px;
  background: rgba(2, 6, 23, 0.48);
  color: rgba(226, 232, 240, 0.80);
  padding: 9px 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.oc-runtime-error {
  margin-top: 10px;
  border: 1px solid rgba(248, 113, 113, 0.22);
  border-radius: 9px;
  background: rgba(127, 29, 29, 0.18);
  color: #fecaca;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.5;
}

.oc-studio-grid {
  width: min(1540px, 100%);
  height: calc(100vh - 184px);
  min-height: 620px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(420px, 1.05fr) minmax(360px, 0.88fr) minmax(300px, 0.72fr);
  gap: 14px;
}

.oc-chat-panel,
.oc-spec-panel,
.oc-context-panel {
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.oc-panel-head {
  min-height: 58px;
  flex: 0 0 auto;
  border-bottom: 1px solid rgba(116, 128, 171, 0.13);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 16px;
}

.oc-panel-head strong {
  display: block;
  color: #111827;
  font-size: 14px;
  font-weight: 780;
}

.oc-panel-head span {
  display: block;
  margin-top: 3px;
  color: #64748b;
  font-size: 11px;
  font-weight: 650;
}

.oc-stage {
  flex: 0 0 auto;
  min-height: 26px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: rgba(83, 109, 254, 0.10);
  color: #4357d4;
  padding: 0 9px;
  font-style: normal;
  font-size: 11px;
  font-weight: 780;
}

.oc-stage.ready,
.oc-stage.confirmed {
  background: rgba(34, 197, 94, 0.10);
  color: #15803d;
}

.oc-stage.building {
  background: rgba(14, 165, 233, 0.10);
  color: #0369a1;
}

.oc-composer {
  flex: 0 0 auto;
  border-top: 1px solid rgba(116, 128, 171, 0.13);
  background: #f8fafc;
  padding: 14px;
}

.oc-composer textarea {
  min-height: 94px;
  max-height: 180px;
}

.oc-composer-bar {
  margin-top: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.oc-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.oc-prompts button {
  min-height: 30px;
  border: 1px solid rgba(116, 128, 171, 0.16);
  border-radius: 9px;
  background: #fff;
  color: #64748b;
  cursor: pointer;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 720;
}

.oc-composer-bar > button {
  min-height: 32px;
  border: 1px solid #151a25;
  border-radius: 9px;
  background: #151a25;
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 11px;
  font-weight: 740;
}

.oc-composer-bar > button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.oc-spec-editor {
  flex: 1;
  min-height: 0;
  resize: none;
  border: 0;
  border-radius: 0;
  background: #fbfcff;
  padding: 16px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.72;
}

.oc-spec-footer {
  min-height: 54px;
  flex: 0 0 auto;
  border-top: 1px solid rgba(116, 128, 171, 0.13);
  background: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
}

.oc-spec-footer span {
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
}

.oc-file-chips {
  flex: 0 0 auto;
  padding: 14px 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-bottom: 1px solid rgba(116, 128, 171, 0.13);
}

.oc-file-chips button {
  max-width: 136px;
  min-height: 27px;
  border: 1px solid rgba(116, 128, 171, 0.16);
  border-radius: 8px;
  background: #fff;
  color: #64748b;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 8px;
  font-size: 11px;
  font-weight: 720;
}

.oc-file-chips button:hover,
.oc-file-chips button.active {
  border-color: rgba(83, 109, 254, 0.32);
  background: rgba(83, 109, 254, 0.08);
  color: #4357d4;
}

.oc-file-preview {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 16px 16px;
}

.oc-file-preview summary {
  cursor: pointer;
  color: #111827;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  font-weight: 780;
}

.oc-file-preview pre {
  max-height: 460px;
  margin: 10px 0 0;
  overflow: auto;
  border-radius: 10px;
  background: #0f172a;
  color: #dbeafe;
  padding: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.65;
}

.oc-empty-text {
  margin-top: 10px;
  color: #64748b;
  font-size: 12px;
}

.oc-ide-pane {
  width: 100%;
  height: calc(100vh - 112px);
  min-height: 460px;
  margin: 0;
  position: relative;
  overflow: hidden;
  background: #111827;
}

.oc-page.is-ide-view.has-preview-panel .oc-ide-pane {
  height: calc(100vh - 154px);
}

.oc-ide-frame {
  width: 100%;
  height: 100%;
  border: 0;
  background: #111827;
}

.oc-ide-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: rgba(246, 248, 252, 0.88);
  color: #475569;
}

.spin {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1100px) {
  .oc-import-shell,
  .oc-planning-shell,
  .oc-studio-grid {
    grid-template-columns: 1fr;
    height: auto;
    min-height: auto;
  }

  .oc-chat-panel,
  .oc-spec-panel,
  .oc-context-panel,
  .oc-plan-chat,
  .oc-import-side {
    min-height: 420px;
  }

  .oc-studio-header {
    flex-direction: column;
  }

  .oc-ide-context span:not(.oc-status-dot):last-child {
    display: none;
  }

  .oc-runtime-meta span {
    max-width: 100%;
  }
}

@media (max-width: 720px) {
  .oc-page {
    padding: 14px;
  }

  .oc-git-shell {
    padding: 16px;
  }

  .oc-token-grid,
  .oc-composer-bar,
  .oc-actions {
    grid-template-columns: 1fr;
    flex-direction: column;
    align-items: stretch;
  }

  .oc-ide-toolbar {
    height: auto;
    min-height: 52px;
    align-items: stretch;
    flex-direction: column;
    padding: 10px 12px;
  }

  .oc-ide-actions {
    width: 100%;
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .oc-runtime-panel {
    padding: 10px 12px;
  }

  .oc-runtime-main {
    flex-direction: column;
    gap: 6px;
  }

  .oc-runtime-main a {
    max-width: 100%;
  }

  .oc-ide-pane {
    height: calc(100vh - 112px);
    min-height: 360px;
  }

  .oc-page.is-ide-view.has-preview-panel .oc-ide-pane {
    height: calc(100vh - 214px);
  }
}

:global(html[data-theme="dark"]) .oc-page {
  background: #0b0f16;
}

:global(html[data-theme="dark"]) .oc-import-main,
:global(html[data-theme="dark"]) .oc-import-side,
:global(html[data-theme="dark"]) .oc-studio-header,
:global(html[data-theme="dark"]) .oc-chat-panel,
:global(html[data-theme="dark"]) .oc-spec-panel,
:global(html[data-theme="dark"]) .oc-context-panel,
:global(html[data-theme="dark"]) .oc-plan-card,
:global(html[data-theme="dark"]) .oc-git-card,
:global(html[data-theme="dark"]) .oc-top-btn,
:global(html[data-theme="dark"]) .oc-secondary,
:global(html[data-theme="dark"]) .oc-mini,
:global(html[data-theme="dark"]) .oc-soft-badge,
:global(html[data-theme="dark"]) .oc-field input,
:global(html[data-theme="dark"]) .oc-field textarea,
:global(html[data-theme="dark"]) .oc-composer textarea,
:global(html[data-theme="dark"]) .oc-spec-editor,
:global(html[data-theme="dark"]) .oc-prompts button,
:global(html[data-theme="dark"]) .oc-file-chips button {
  background: #111318;
  border-color: rgba(148, 163, 184, 0.14);
  color: rgba(226, 232, 240, 0.86);
  box-shadow: none;
}

:global(html[data-theme="dark"]) .oc-import-main h1,
:global(html[data-theme="dark"]) .oc-studio-header h1,
:global(html[data-theme="dark"]) .oc-panel-head strong,
:global(html[data-theme="dark"]) .oc-file-preview summary {
  color: rgba(248, 250, 252, 0.94);
}

:global(html[data-theme="dark"]) .oc-import-main p,
:global(html[data-theme="dark"]) .oc-studio-header p,
:global(html[data-theme="dark"]) .oc-panel-head span,
:global(html[data-theme="dark"]) .oc-spec-footer span,
:global(html[data-theme="dark"]) .oc-empty-text {
  color: rgba(203, 213, 225, 0.66);
}

:global(html[data-theme="dark"]) .oc-panel-head,
:global(html[data-theme="dark"]) .oc-composer,
:global(html[data-theme="dark"]) .oc-spec-footer,
:global(html[data-theme="dark"]) .oc-file-chips,
:global(html[data-theme="dark"]) .oc-plan-spec-editor {
  background: rgba(13, 17, 23, 0.82);
  border-color: rgba(148, 163, 184, 0.14);
}

:global(html[data-theme="dark"]) .oc-primary,
:global(html[data-theme="dark"]) .oc-composer-bar > button {
  background: #eef2ff;
  border-color: #eef2ff;
  color: #111318;
}
</style>

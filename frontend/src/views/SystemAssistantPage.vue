<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AgentConversation from '@/components/common/AgentConversation.vue'
import AgentRunTraceDrawer from '@/components/common/AgentRunTraceDrawer.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import BuilderModelPicker from '@/components/common/BuilderModelPicker.vue'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import type { AgentMessage } from '@/components/common/agent-conversation/types'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'
import { aiChatApi } from '@/api/aiChat'
import type { BuilderModelOption } from '@/api/llmConfig'
import {
  systemAssistantApi,
  type SystemAssistantBootstrap,
} from '@/api/systemAssistant'
import { listSkills } from '@/api/skills'
import { useAiChatSession } from '@/composables/useAiChatSession'
import { isImageFile } from '@/utils/pasteImages'
import ArtifactPanel from '@/views/workspace/panels/ArtifactPanel.vue'
import SystemAssistantBaseline from './system-assistant/SystemAssistantBaseline.vue'

const route = useRoute()
const router = useRouter()
const selectedLlmId = ref<number | null>(null)
const llmOptions = ref<BuilderModelOption[]>([])

const {
  currentSession,
  sessions,
  agentMessages,
  typing,
  typingSeconds,
  sending,
  currentRunId,
  loadSessions,
  loadSession,
  newSession,
  send,
  stop,
} = useAiChatSession({
  mode: 'code',
  assistantProfile: 'system_assistant',
  selectedLlmId,
})

const bootstrap = ref<SystemAssistantBootstrap | null>(null)
const bootstrapLoading = ref(true)
const bootstrapError = ref('')
const inputText = ref('')
const pendingFiles = ref<File[]>([])
const availableSkills = ref<{ name: string; description: string }[]>([])
const traceDrawerVisible = ref(false)
const tracePreferRunId = ref<string | null>(null)
const artifactDrawerVisible = ref(false)
const activeArtifact = ref<any>(null)

const hasConversation = computed(() => agentMessages.value.length > 0 || Boolean(currentSession.value))
const currentSessionTitle = computed(() => {
  const id = currentSession.value?.id
  const latest = id == null ? null : sessions.value.find(session => session.id === id)
  return latest?.title?.trim() || currentSession.value?.title?.trim() || '企业 Code 能力与工程协作'
})
const composerAttachments = computed<UnifiedChatAttachment[]>(() =>
  pendingFiles.value.map((file, index) => ({
    id: index,
    name: file.name,
    kind: isImageFile(file) ? 'image' : 'file',
  })),
)

function querySessionId(): number | null {
  const raw = Array.isArray(route.query.session) ? route.query.session[0] : route.query.session
  const value = Number(raw)
  return Number.isInteger(value) && value > 0 ? value : null
}

function syncSelectedLlmFromSession() {
  const sessionLlm = currentSession.value?.selected_llm_config_id ?? null
  const ids = new Set(llmOptions.value.map(option => option.id))
  selectedLlmId.value = sessionLlm != null && ids.has(sessionLlm)
    ? sessionLlm
    : (llmOptions.value.find(option => option.is_default)?.id ?? null)
}

async function loadBootstrap() {
  bootstrapLoading.value = true
  bootstrapError.value = ''
  try {
    bootstrap.value = await systemAssistantApi.getBootstrap()
  } catch (error: any) {
    bootstrapError.value = error?.response?.data?.detail || error?.message || '企业 Code 基线暂时无法读取'
  } finally {
    bootstrapLoading.value = false
  }
}

async function loadModels() {
  try {
    llmOptions.value = await systemAssistantApi.listModels()
    syncSelectedLlmFromSession()
  } catch {
    llmOptions.value = []
    selectedLlmId.value = null
  }
}

async function selectSession(id: number | null) {
  if (id == null) {
    newSession()
    return
  }
  if (currentSession.value?.id === id) return
  try {
    await loadSession(id)
    syncSelectedLlmFromSession()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '加载会话失败')
  }
}

watch(
  () => route.query.session,
  () => { void selectSession(querySessionId()) },
)

watch(
  () => currentSession.value?.id ?? null,
  (id) => {
    const current = querySessionId()
    if (id === current) return
    const query = { ...route.query }
    if (id == null) delete query.session
    else query.session = String(id)
    router.replace({ path: '/code/system-assistant', query }).catch(() => {})
    window.dispatchEvent(new CustomEvent('code-rail-refresh'))
  },
)

watch(sending, () => {
  window.dispatchEvent(new CustomEvent('code-rail-refresh'))
})

function createSession() {
  newSession()
  const query = { ...route.query }
  delete query.session
  router.replace({ path: '/code/system-assistant', query }).catch(() => {})
}

function onComposerFilesPicked(files: File[]) {
  if (files.length) pendingFiles.value = [...pendingFiles.value, ...files]
}

function removePendingFile(_: UnifiedChatAttachment, index: number) {
  pendingFiles.value = pendingFiles.value.filter((_, itemIndex) => itemIndex !== index)
}

function onSkillPicked(name: string) {
  const prefix = `请使用技能 ${name}：`
  inputText.value = inputText.value ? `${prefix}${inputText.value}` : prefix
}

async function doSend() {
  const text = inputText.value.trim()
  if ((!text && pendingFiles.value.length === 0) || sending.value) return
  const files = pendingFiles.value.slice()
  inputText.value = ''
  pendingFiles.value = []
  try {
    await send(text, files.length ? files : undefined)
    await loadSessions()
  } catch (error: any) {
    inputText.value = text
    pendingFiles.value = files
    ElMessage.error(error?.response?.data?.detail || error?.message || '发送失败')
  }
}

async function onStop() {
  try { await stop() } catch { /* run status will reconcile on reload */ }
}

async function onChangeLlm() {
  if (!currentSession.value) return
  try {
    const updated = await aiChatApi.updateSession(currentSession.value.id, {
      selected_llm_config_id: selectedLlmId.value ?? 0,
    })
    currentSession.value.selected_llm_config_id = updated.selected_llm_config_id
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '切换模型失败')
  }
}

function openTrace(message?: AgentMessage) {
  tracePreferRunId.value = (message?.meta as any)?.run_id || currentRunId.value
  traceDrawerVisible.value = true
}

function openArtifact(artifact: any) {
  activeArtifact.value = artifact
  artifactDrawerVisible.value = true
}

function onSessionRenamed(event: Event) {
  const detail = (event as CustomEvent<{ id?: number; title?: string }>).detail
  const id = Number(detail?.id)
  const title = String(detail?.title || '').trim()
  if (!Number.isInteger(id) || !title) return
  const session = sessions.value.find(item => item.id === id)
  if (session) session.title = title
  if (currentSession.value?.id === id) currentSession.value.title = title
}

onMounted(async () => {
  window.addEventListener('system-assistant-session-renamed', onSessionRenamed)
  await Promise.all([
    loadBootstrap(),
    loadModels(),
    loadSessions(),
    listSkills().then(value => { availableSkills.value = value }).catch(() => {}),
  ])
  await selectSession(querySessionId())
})

onBeforeUnmount(() => {
  window.removeEventListener('system-assistant-session-renamed', onSessionRenamed)
})
</script>

<template>
  <div class="system-assistant-page">
    <header class="system-assistant-header">
      <div class="system-assistant-heading">
        <span class="system-assistant-logo"><AppIcon name="sparkles" :size="16" /></span>
        <div>
          <strong>系统助手</strong>
          <span :title="currentSessionTitle">{{ currentSessionTitle }}</span>
        </div>
      </div>
      <div class="system-assistant-actions">
        <button type="button" class="header-icon-button" title="刷新基线" @click="loadBootstrap">
          <AppIcon name="refresh" :size="15" />
        </button>
        <button v-if="currentSession" type="button" class="header-icon-button" title="查看执行记录" @click="openTrace()">
          <AppIcon name="flow" :size="15" />
        </button>
        <button type="button" class="new-session-button" @click="createSession">
          <AppIcon name="plus" :size="14" />
          新会话
        </button>
      </div>
    </header>

    <div v-if="bootstrapError" class="baseline-error">
      <span>{{ bootstrapError }}</span>
      <button type="button" @click="loadBootstrap">重试</button>
    </div>

    <AgentConversation
      class="system-assistant-conversation"
      :messages="agentMessages"
      :typing="typing"
      :typing-seconds="typingSeconds"
      :loading="bootstrapLoading"
      :tool-grouping="true"
      empty-title="系统助手"
      empty-hint="描述你要诊断、建设或修改的工程与系统能力"
      @answer-ask="option => send(option)"
      @open-trace="openTrace"
      @open-artifact="openArtifact"
    >
      <template #list-prefix>
        <SystemAssistantBaseline
          v-if="bootstrap"
          :bootstrap="bootstrap"
          :compact="hasConversation"
        />
      </template>
    </AgentConversation>

    <div class="system-assistant-composer">
      <UnifiedChatComposer
        v-model="inputText"
        :attachments="composerAttachments"
        :sending="sending"
        :send-disabled="!inputText.trim() && pendingFiles.length === 0"
        :multiple="true"
        :skills="availableSkills"
        placeholder="询问工程、环境、能力、知识或 Skill，也可以直接上传文件..."
        hint=""
        sending-hint="任务运行中，可继续编辑下一条消息"
        @send="doSend"
        @stop="onStop"
        @files-picked="onComposerFilesPicked"
        @skill-picked="onSkillPicked"
        @remove-attachment="removePendingFile"
      >
        <template #footer-left>
          <BuilderModelPicker
            v-model="selectedLlmId"
            :options="llmOptions"
            title="切换 Code 模型"
            default-label="默认 Code 模型"
            :show-default-config-name="true"
            @change="onChangeLlm"
          />
        </template>
      </UnifiedChatComposer>
    </div>

    <AgentRunTraceDrawer
      v-model="traceDrawerVisible"
      :session-id="currentSession?.id ?? null"
      :prefer-run-id="tracePreferRunId"
    />

    <el-drawer v-model="artifactDrawerVisible" title="会话产物" size="min(720px, 92vw)">
      <ArtifactPanel :session-id="currentSession?.id ?? null" :artifact="activeArtifact" />
    </el-drawer>
  </div>
</template>

<style scoped>
.system-assistant-page {
  min-width: 0;
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface);
}

.system-assistant-header {
  min-height: 54px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 16px 8px 18px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}

.system-assistant-heading,
.system-assistant-actions {
  display: flex;
  align-items: center;
}

.system-assistant-heading {
  min-width: 0;
  gap: 10px;
}

.system-assistant-logo {
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: color-mix(in srgb, var(--brand) 13%, var(--surface));
  color: var(--brand);
}

.system-assistant-heading > div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.system-assistant-heading strong {
  color: var(--text);
  font-size: 13.5px;
  font-weight: 650;
}

.system-assistant-heading span:last-child {
  overflow: hidden;
  color: var(--text-4);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.system-assistant-actions {
  gap: 7px;
}

.header-icon-button,
.new-session-button {
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
  color: var(--text-3);
  cursor: pointer;
  font: inherit;
}

.header-icon-button {
  width: 32px;
  padding: 0;
}

.new-session-button {
  gap: 6px;
  padding: 0 11px;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}

.header-icon-button:hover,
.new-session-button:hover {
  border-color: color-mix(in srgb, var(--brand) 42%, var(--line));
  background: var(--brand-soft);
  color: var(--brand);
}

.baseline-error {
  margin: 10px 16px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 11px;
  border: 1px solid color-mix(in srgb, var(--danger, #dc2626) 28%, var(--line));
  border-radius: 7px;
  background: color-mix(in srgb, var(--danger, #dc2626) 7%, var(--surface));
  color: var(--text-2);
  font-size: 12px;
}

.baseline-error button {
  border: 0;
  background: transparent;
  color: var(--brand);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
}

.system-assistant-conversation {
  min-height: 0;
  flex: 1;
}

.system-assistant-conversation :deep(.ac-list) {
  padding-inline: max(16px, calc((100% - 820px) / 2));
}

.system-assistant-composer {
  flex: 0 0 auto;
  padding: 10px max(16px, calc((100% - 820px) / 2)) 14px;
  border-top: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
  background: var(--surface);
}

.system-assistant-composer :deep(.ucc-box),
.system-assistant-composer :deep(.ucc-footer),
.system-assistant-composer :deep(.ucc-footer-left) {
  overflow: visible;
}

.system-assistant-composer :deep(.ucc-send) {
  position: absolute;
  right: 8px;
  bottom: 8px;
  z-index: 2;
  width: 36px;
  height: 36px;
  min-height: 36px;
}

.system-assistant-composer :deep(.ucc-footer) {
  padding-right: 52px;
}

@media (max-width: 720px) {
  .system-assistant-header {
    padding-inline: 12px;
  }

  .system-assistant-heading span:last-child {
    display: none;
  }

  .new-session-button {
    width: 32px;
    padding: 0;
    overflow: hidden;
    color: transparent;
    gap: 0;
  }

  .new-session-button :deep(.app-icon) {
    color: var(--text-3);
  }

  .system-assistant-composer {
    padding: 8px 10px 10px;
  }

  .system-assistant-conversation :deep(.ac-list) {
    padding-inline: 10px;
  }
}
</style>

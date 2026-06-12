<template>
  <BuilderFrame :breadcrumbs="[{ label: '设置' }, { label: 'Agent 提示词' }]">
    <template #actions>
      <span class="ap-hint">改提示词不发版 · 当前租户生效</span>
    </template>

    <main class="ap-main builder-page">
      <!-- agent 选择 -->
      <section class="ap-tabs">
        <button
          v-for="a in agents"
          :key="a.id"
          class="ap-tab"
          :class="{ active: activeAgent === a.id }"
          @click="selectAgent(a.id)"
        >
          {{ a.label }}
        </button>
      </section>

      <p class="ap-agent-desc">{{ activeAgentDesc }}</p>

      <div v-if="loading" class="ap-state">
        <SkeletonCard :lines="4" with-footer />
      </div>
      <div v-else-if="error" class="ap-state error">
        <ErrorCard
          level="err"
          title="拉取提示词失败"
          :message="error"
          :actions="[{ label: '重试', primary: true, onClick: () => load() }]"
        />
      </div>

      <template v-else>
        <section v-if="prompts.length === 0" class="ap-empty">
          <EmptyState
            title="该 agent 暂无提示词"
            desc="首次访问会自动落库默认提示词；若仍为空，说明后端尚未为该 agent 配置默认模板。"
          />
        </section>

        <el-table v-else :data="prompts" class="ap-table" border>
          <el-table-column prop="phase" label="阶段 (phase)" width="200">
            <template #default="{ row }">
              <code class="ap-phase">{{ row.phase }}</code>
            </template>
          </el-table-column>
          <el-table-column label="模板预览">
            <template #default="{ row }">
              <span class="ap-preview">{{ previewOf(row.template) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="version" label="版本" width="90" align="center">
            <template #default="{ row }">
              <span class="ap-version">v{{ row.version }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click="openEdit(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- 编辑抽屉 -->
      <el-drawer
        v-model="drawer.open"
        :title="drawer.title"
        size="56%"
        direction="rtl"
        :close-on-click-modal="false"
      >
        <div class="ap-drawer-body">
          <div class="ap-field">
            <label class="ap-label">模板内容</label>
            <p class="ap-field-hint">
              这里只保存<strong>静态模板</strong>。运行时动态拼接（如 app 上下文）由后端代码完成，不在此编辑。
            </p>
            <textarea
              v-model="drawer.template"
              class="ap-textarea"
              spellcheck="false"
              placeholder="提示词模板…"
            ></textarea>
            <div class="ap-meta-line">
              <span>{{ drawer.template.length }} 字符</span>
            </div>
          </div>

          <div class="ap-field">
            <label class="ap-label">备注 (可选)</label>
            <input v-model="drawer.notes" class="ap-input" placeholder="为什么这么改 / 何时用…" />
          </div>
        </div>

        <template #footer>
          <div class="ap-drawer-footer">
            <el-button @click="drawer.open = false">取消</el-button>
            <el-button type="primary" :loading="drawer.saving" @click="save">保存</el-button>
          </div>
        </template>
      </el-drawer>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorCard from '@/components/states/ErrorCard.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import {
  agentPromptsApi,
  AGENT_DESCRIPTORS,
  type AgentPromptItem,
} from '@/api/agentPrompts'

const agents = AGENT_DESCRIPTORS

const activeAgent = ref<string>(agents[0].id)
const loading = ref(true)
const error = ref('')
const prompts = ref<AgentPromptItem[]>([])

const activeAgentDesc = computed(
  () => agents.find(a => a.id === activeAgent.value)?.desc || '',
)

interface DrawerState {
  open: boolean
  title: string
  phase: string
  template: string
  notes: string
  saving: boolean
}
const drawer = reactive<DrawerState>({
  open: false,
  title: '',
  phase: '',
  template: '',
  notes: '',
  saving: false,
})

function previewOf(t: string): string {
  const flat = (t || '').replace(/\s+/g, ' ').trim()
  return flat.length > 120 ? flat.slice(0, 120) + '…' : flat
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await agentPromptsApi.list(activeAgent.value)
    prompts.value = data.prompts
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function selectAgent(id: string) {
  if (id === activeAgent.value) return
  activeAgent.value = id
  load()
}

function openEdit(row: AgentPromptItem) {
  drawer.title = `编辑 · ${activeAgent.value} / ${row.phase}`
  drawer.phase = row.phase
  drawer.template = row.template
  drawer.notes = row.notes || ''
  drawer.saving = false
  drawer.open = true
}

async function save() {
  if (!drawer.template.trim()) {
    ElMessage.warning('模板内容不能为空')
    return
  }
  drawer.saving = true
  try {
    await agentPromptsApi.update(activeAgent.value, drawer.phase, {
      template: drawer.template,
      notes: drawer.notes || null,
    })
    ElMessage.success('已保存，下次对话即生效（无需发版）')
    drawer.open = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存失败')
  } finally {
    drawer.saving = false
  }
}

onMounted(() => { load() })
</script>

<style scoped>
.ap-main {
  padding: 16px 24px 40px;
  background: var(--bg);
  min-height: 100%;
}
.ap-hint {
  font-size: var(--t-small, 12.5px);
  color: var(--text-3);
}

.ap-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.ap-tab {
  padding: 6px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-full, 999px);
  background: var(--surface);
  color: var(--text-2);
  font-size: var(--t-small, 12.5px);
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.14s var(--ease), background 0.14s var(--ease), color 0.14s var(--ease);
}
.ap-tab:hover {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  color: var(--brand);
}
.ap-tab.active {
  background: var(--brand);
  color: var(--text-inverse);
  border-color: var(--brand);
}

.ap-agent-desc {
  font-size: var(--t-small, 12.5px);
  color: var(--text-3);
  margin: 0 0 16px;
}

.ap-state {
  padding: 32px;
  text-align: center;
  color: var(--text-3);
  font-size: var(--t-body, 14px);
}
.ap-state.error { color: var(--err); }
.ap-empty { padding: 24px; }

.ap-table { width: 100%; }
.ap-phase {
  font-family: var(--font-mono);
  font-size: var(--t-small, 12.5px);
  color: var(--brand);
  font-weight: var(--fw-semibold, 600);
}
.ap-preview {
  font-size: var(--t-small, 12.5px);
  color: var(--text-2);
  line-height: 1.5;
}
.ap-version {
  font-family: var(--font-mono);
  font-size: var(--t-micro, 11px);
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

.ap-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 0 4px;
}
.ap-field { display: flex; flex-direction: column; gap: 6px; }
.ap-label {
  font-size: var(--t-small, 12.5px);
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}
.ap-field-hint {
  margin: 0;
  font-size: var(--t-micro, 11px);
  color: var(--text-3);
  line-height: 1.5;
}
.ap-textarea {
  width: 100%;
  min-height: 420px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  font-family: var(--font-mono);
  font-size: var(--t-mono, 12px);
  resize: vertical;
  outline: none;
  background: var(--surface-2);
  color: var(--text);
  line-height: 1.6;
  transition: border-color 0.14s var(--ease), box-shadow 0.14s var(--ease);
}
.ap-textarea:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
  background: var(--surface);
}
.ap-input {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  font-size: var(--t-body, 14px);
  background: var(--surface);
  color: var(--text);
  outline: none;
  font-family: inherit;
  transition: border-color 0.14s var(--ease), box-shadow 0.14s var(--ease);
}
.ap-input:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
}
.ap-meta-line {
  display: flex;
  justify-content: flex-end;
  font-size: var(--t-micro, 11px);
  color: var(--text-4);
  font-variant-numeric: tabular-nums;
}
.ap-drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>

<template>
  <div class="git-bar">
    <!-- 📁 工作区:显当前 + 切(切=开新会话,由父处理) -->
    <el-dropdown trigger="click" @command="onSwitchWorkspace">
      <button class="git-chip" title="切换工作区">
        <AppIcon name="folder" :size="13" /> {{ workspaceName || wsId }} <span class="caret">▾</span>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="w in workspaces"
            :key="w.ws_id || w.id"
            :command="w.ws_id || w.id"
          >
            {{ w.project_name || w.name || (w.ws_id || w.id) }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>

    <!-- ⎇ 分支:显当前 + 列/切/建 -->
    <el-dropdown trigger="click" @command="onPickBranch">
      <button class="git-chip" title="切换分支">
        <!-- inline SVG for git-branch (not in ICON_PATHS) -->
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="6" r="3"/>
          <path d="M6 9v6M6 9a9 9 0 0 0 9 9"/>
        </svg>
        {{ branch || '—' }}<span v-if="dirty" class="dot" title="有未提交改动">●</span> <span class="caret">▾</span>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-for="b in branches" :key="b" :command="b">{{ b }}</el-dropdown-item>
          <el-dropdown-item divided command="__new__">+ 新建分支…</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>

    <!-- 远程仓段:未连 → [连接 git];已连 → ↑n↓n + push/pull -->
    <template v-if="hasRemote === false">
      <button class="git-chip git-action" @click="openConnectDialog" title="连接远程 git 仓库">
        连接 git
      </button>
    </template>
    <template v-else-if="hasRemote === true">
      <span class="git-remote-status" title="↑ ahead ↓ behind">↑{{ ahead }} ↓{{ behind }}</span>
      <button class="git-chip git-action" :disabled="pushing" @click="onPush">
        {{ pushing ? '推送中…' : 'push' }}
      </button>
      <button class="git-chip git-action" :disabled="pulling" @click="onPull">
        {{ pulling ? '拉取中…' : 'pull' }}
      </button>
    </template>

    <!-- 连接 git 弹窗 -->
    <el-dialog
      v-model="connectDialogVisible"
      title="连接远程 git 仓库"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form label-width="90px" class="connect-form">
        <el-form-item label="平台">
          <el-select v-model="connectForm.provider" placeholder="选择平台">
            <el-option label="GitLab" value="gitlab" />
            <el-option label="GitHub" value="github" />
          </el-select>
        </el-form-item>
        <el-form-item label="仓库 URL">
          <el-input
            v-model="connectForm.remote_url"
            placeholder="https://gitlab.example.com/group/repo.git"
            clearable
          />
        </el-form-item>
        <el-form-item label="凭证 ID">
          <el-input
            v-model.number="connectForm.git_connection_id_str"
            placeholder="git_connections 表的 id（整数）"
            clearable
          />
          <div class="connect-hint">
            凭证 ID 在「项目设置 → git 连接」里查看。如尚未创建，请先去平台连接 git 凭证。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="connectDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="connecting" @click="onConfirmConnect">确认连接</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { codingApi } from '@/api/coding'
import AppIcon from '@/components/common/AppIcon.vue'

const props = defineProps<{
  wsId: string
  workspaceName?: string
  workspaces?: any[]
}>()

const emit = defineEmits<{
  (e: 'switch-workspace', wsId: string): void
}>()

const branch = ref('')
const dirty = ref(false)
const branches = ref<string[]>([])

// P2: 远程状态
const hasRemote = ref<boolean | null>(null)
const ahead = ref(0)
const behind = ref(0)

// 连接弹窗
const connectDialogVisible = ref(false)
const connecting = ref(false)
const connectForm = ref({
  provider: 'gitlab' as 'gitlab' | 'github',
  remote_url: '',
  git_connection_id_str: '' as string | number,
})

// push/pull 加载态
const pushing = ref(false)
const pulling = ref(false)

async function refresh() {
  if (!props.wsId) return
  try {
    const s = await codingApi.gitStatus(props.wsId)
    branch.value = s.branch
    dirty.value = s.dirty
    hasRemote.value = s.has_remote ?? null
    if (s.has_remote) {
      ahead.value = (s as any).ahead ?? 0
      behind.value = (s as any).behind ?? 0
    }
    branches.value = (await codingApi.gitBranches(props.wsId)).local
  } catch {
    // 工作区可能非 git 仓 → 静默忽略
  }
}

watch(() => props.wsId, refresh, { immediate: true })

function onSwitchWorkspace(wsId: string) {
  if (wsId && wsId !== props.wsId) emit('switch-workspace', wsId)
}

async function onPickBranch(cmd: string) {
  if (cmd === '__new__') {
    try {
      const { value } = await ElMessageBox.prompt('新分支名', '新建分支', {
        inputPattern: /\S+/,
        inputErrorMessage: '不能为空',
      })
      await codingApi.gitCheckout(props.wsId, { name: value.trim(), create: true })
      ElMessage.success(`已切到新分支 ${value.trim()}`)
      await refresh()
    } catch (e: any) {
      if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '建分支失败')
    }
    return
  }
  if (cmd === branch.value) return
  try {
    await codingApi.gitCheckout(props.wsId, { name: cmd, create: false })
    ElMessage.success(`已切到 ${cmd}`)
    await refresh()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '切分支失败')
  }
}

function openConnectDialog() {
  connectForm.value = { provider: 'gitlab', remote_url: '', git_connection_id_str: '' }
  connectDialogVisible.value = true
}

async function onConfirmConnect() {
  const { provider, remote_url, git_connection_id_str } = connectForm.value
  const git_connection_id = Number(git_connection_id_str)
  if (!remote_url.trim()) {
    ElMessage.warning('请填写仓库 URL')
    return
  }
  if (!git_connection_id || isNaN(git_connection_id)) {
    ElMessage.warning('请填写有效的凭证 ID（整数）')
    return
  }
  connecting.value = true
  try {
    const res = await codingApi.gitConnect(props.wsId, { provider, remote_url: remote_url.trim(), git_connection_id })
    ElMessage.success(`已连接远程仓，默认分支: ${res.default_branch}`)
    connectDialogVisible.value = false
    await refresh()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '连接失败，请检查 URL 和凭证')
  } finally {
    connecting.value = false
  }
}

async function onPush() {
  pushing.value = true
  try {
    await codingApi.gitPush(props.wsId)
    ElMessage.success('push 成功')
    await refresh()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'push 失败')
  } finally {
    pushing.value = false
  }
}

async function onPull() {
  pulling.value = true
  try {
    await codingApi.gitPull(props.wsId)
    ElMessage.success('pull 成功')
    await refresh()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'pull 失败')
  } finally {
    pulling.value = false
  }
}
</script>

<style scoped>
.git-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 4px 0;
}

.git-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 3px 8px;
  border: 1px solid var(--ac-border, #cbd5e1);
  border-radius: 6px;
  background: var(--ac-btn, #fff);
  color: var(--ac-text-mute, #475569);
  cursor: pointer;
}

.git-chip:hover {
  background: var(--ac-input, #f8fafc);
}

.git-chip:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.git-action {
  font-size: 11px;
  padding: 2px 7px;
}

.caret {
  opacity: 0.6;
}

.dot {
  color: #f59e0b;
  margin-left: 2px;
}

.git-remote-status {
  font-size: 11px;
  color: var(--ac-text-mute, #475569);
  font-variant-numeric: tabular-nums;
}

.connect-form {
  padding: 0 4px;
}

.connect-hint {
  font-size: 12px;
  color: var(--ac-text-mute, #94a3b8);
  margin-top: 4px;
  line-height: 1.5;
}
</style>

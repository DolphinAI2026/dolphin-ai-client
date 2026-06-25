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

async function refresh() {
  if (!props.wsId) return
  try {
    const s = await codingApi.gitStatus(props.wsId)
    branch.value = s.branch
    dirty.value = s.dirty
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

.caret {
  opacity: 0.6;
}

.dot {
  color: #f59e0b;
  margin-left: 2px;
}
</style>

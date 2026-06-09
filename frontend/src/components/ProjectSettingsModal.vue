<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '应用设置' : '新建应用'"
    width="640px"
    :close-on-click-modal="false"
    class="project-settings-modal"
  >
    <div class="settings-layout">
      <!-- 左侧 Tabs -->
      <div class="settings-tabs">
        <div
          class="settings-tab-item"
          :class="{ active: activeTab === 'basic' }"
          @click="activeTab = 'basic'"
        >
          基本信息
        </div>
        <template v-if="isEdit">
          <div
            class="settings-tab-item"
            :class="{ active: activeTab === 'team' }"
            @click="activeTab = 'team'"
          >
            团队成员
          </div>
        </template>
      </div>

      <!-- 右侧内容区 -->
      <div class="settings-content">
        <!-- 基本信息 -->
        <div v-show="activeTab === 'basic'" class="settings-pane">
          <el-form :model="form" label-position="top" size="default">
            <el-form-item label="应用名称" required>
              <el-input v-model="form.name" :disabled="!canEditProject" placeholder="例如：劳务管理系统" />
            </el-form-item>
            <el-form-item label="应用描述">
              <el-input v-model="form.description" :disabled="!canEditProject" type="textarea" :rows="3" placeholder="简要描述应用用途" />
            </el-form-item>
          </el-form>
        </div>

        <!-- 团队成员 -->
        <div v-if="isEdit" v-show="activeTab === 'team'" class="settings-pane">
          <div class="team-members-section">
            <!-- 添加成员 -->
            <div v-if="canManageMembers" class="add-member-row">
              <el-select
                v-model="selectedUserId"
                filterable
                placeholder="选择用户"
                size="small"
                style="flex: 1"
                :loading="loadingUsers"
                @focus="fetchAvailableUsers"
              >
                <el-option
                  v-for="u in availableUsers"
                  :key="u.id"
                  :label="u.username"
                  :value="u.id"
                />
              </el-select>
              <el-select v-model="newMemberRole" size="small" style="width: 100px; margin-left: 8px">
                <el-option label="管理员" value="admin" />
                <el-option label="成员" value="member" />
              </el-select>
              <el-button
                type="primary"
                size="small"
                :loading="addingMember"
                :disabled="!selectedUserId"
                style="margin-left: 8px"
                @click="handleAddMember"
              >
                添加
              </el-button>
            </div>
            <el-alert
              v-else
              type="info"
              :closable="false"
              show-icon
              style="margin-bottom: 12px"
            >
              当前角色只能查看团队成员，添加/移除成员需要项目管理员权限。
            </el-alert>

            <!-- 成员列表 -->
            <div v-if="loadingMembers" class="members-loading">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>加载中...</span>
            </div>
            <div v-else class="members-list">
              <div v-for="member in members" :key="member.id" class="member-item">
                <span class="member-name">{{ member.username }}</span>
                <el-tag
                  :type="member.role === 'owner' ? 'warning' : member.role === 'admin' ? 'primary' : 'info'"
                  size="small"
                  class="member-role-tag"
                >
                  {{ member.role === 'owner' ? '所有者' : member.role === 'admin' ? '管理员' : '成员' }}
                </el-tag>
                <template v-if="member.role !== 'owner'">
                  <el-select
                    :model-value="member.role"
                    :disabled="!canManageMemberRoles"
                    size="small"
                    style="width: 90px; margin-left: auto"
                    @change="(val: string) => handleUpdateRole(member, val)"
                  >
                    <el-option label="管理员" value="admin" />
                    <el-option label="成员" value="member" />
                  </el-select>
                  <el-button
                    v-if="canManageMembers"
                    type="danger"
                    size="small"
                    text
                    style="margin-left: 4px"
                    @click="handleRemoveMember(member)"
                  >
                    <el-icon><Close /></el-icon>
                  </el-button>
                </template>
              </div>
              <div v-if="!members.length" class="no-members">暂无成员</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button v-if="canEditProject" type="primary" :loading="saving" @click="handleSave">
        {{ isEdit ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import request from '@/utils/request'
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, Close } from '@element-plus/icons-vue'
import { projectsApi } from '@/api/projects'
import type { Project, ProjectMember } from '@/api/projects'

const props = defineProps<{
  project?: Project | null
}>()

const emit = defineEmits<{
  saved: [project: Project]
}>()

const visible = defineModel<boolean>({ default: false })

const isEdit = computed(() => !!props.project?.id)
const activeTab = ref('basic')
const canEditProject = computed(() => !isEdit.value || !!props.project?.can_manage_project)
const canManageMembers = computed(() => !!props.project?.can_manage_members)
const canManageMemberRoles = computed(() => !!props.project?.can_manage_member_roles)

const form = reactive({
  name: '',
  description: '',
})

const saving = ref(false)

// 团队成员
const members = ref<ProjectMember[]>([])
const loadingMembers = ref(false)
const addingMember = ref(false)
const selectedUserId = ref<number | null>(null)
const newMemberRole = ref('member')
const availableUsers = ref<{ id: number; username: string }[]>([])
const loadingUsers = ref(false)

// Watch for project changes to populate form
watch(() => props.project, (p) => {
  if (p) {
    form.name = p.name || ''
    form.description = p.description || ''
    // 加载成员列表
    fetchMembers()
  } else {
    form.name = ''
    form.description = ''
    members.value = []
    selectedUserId.value = null
    newMemberRole.value = 'member'
    availableUsers.value = []
  }
  // Reset to basic tab when dialog opens
  activeTab.value = 'basic'
}, { immediate: true })

async function fetchMembers() {
  if (!props.project?.id) return
  loadingMembers.value = true
  try {
    members.value = await projectsApi.listMembers(props.project.id)
  } catch (e: any) {
    console.error('获取成员列表失败:', e)
    members.value = []
  } finally {
    loadingMembers.value = false
  }
}

async function fetchAvailableUsers() {
  if (availableUsers.value.length > 0) return
  loadingUsers.value = true
  try {
    const allUsers = await request.get<any, { id: number; username: string }[]>('/auth/users')
    const memberIds = new Set(members.value.map(m => m.user_id))
    availableUsers.value = (allUsers || []).filter(u => !memberIds.has(u.id))
  } catch (e) {
    console.error('获取用户列表失败', e)
  } finally {
    loadingUsers.value = false
  }
}

async function handleAddMember() {
  if (!canManageMembers.value) {
    ElMessage.warning('当前角色无权添加成员')
    return
  }
  if (!props.project?.id) {
    ElMessage.warning('请先保存应用')
    return
  }
  if (!selectedUserId.value) {
    ElMessage.warning('请选择用户')
    return
  }
  addingMember.value = true
  try {
    const member = await projectsApi.addMember(props.project.id, {
      user_id: selectedUserId.value,
      role: newMemberRole.value,
    })
    members.value.push(member)
    selectedUserId.value = null
    newMemberRole.value = 'member'
    // 刷新可选用户列表
    availableUsers.value = availableUsers.value.filter(u => u.id !== member.user_id)
    ElMessage.success('成员已添加')
  } catch (e: any) {
    ElMessage.error(e.message || '添加成员失败')
  } finally {
    addingMember.value = false
  }
}

async function handleRemoveMember(member: ProjectMember) {
  if (!canManageMembers.value) {
    ElMessage.warning('当前角色无权移除成员')
    return
  }
  if (!props.project?.id) return
  try {
    await ElMessageBox.confirm(`确定移除成员 ${member.username}？`, '确认移除', {
      confirmButtonText: '移除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await projectsApi.removeMember(props.project.id, member.id)
    members.value = members.value.filter(m => m.id !== member.id)
    ElMessage.success('成员已移除')
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.message || '移除失败')
    }
  }
}

async function handleUpdateRole(member: ProjectMember, newRole: string) {
  if (!canManageMemberRoles.value) {
    ElMessage.warning('当前角色无权修改成员角色')
    return
  }
  if (!props.project?.id) return
  try {
    await projectsApi.updateMemberRole(props.project.id, member.id, newRole)
    member.role = newRole as ProjectMember['role']
    ElMessage.success('角色已更新')
  } catch (e: any) {
    ElMessage.error(e.message || '更新角色失败')
  }
}

async function handleSave() {
  if (!canEditProject.value) {
    ElMessage.warning('当前角色无权修改项目')
    return
  }
  if (!form.name.trim()) {
    ElMessage.warning('请输入应用名称')
    return
  }
  saving.value = true
  try {
    let result: Project
    if (isEdit.value && props.project?.id) {
      // Update existing project
      const updateData: Record<string, any> = {
        name: form.name,
        description: form.description,
      }
      result = await projectsApi.update(props.project.id, updateData)
    } else {
      // Create new project
      result = await projectsApi.create({
        name: form.name,
        description: form.description,
      })
    }
    ElMessage.success(isEdit.value ? '应用已保存' : '应用已创建')
    emit('saved', result)
    visible.value = false
  } catch (e: any) {
    ElMessage.error(e.message || '操作失败')
  } finally {
    saving.value = false
  }
}
</script>

<style lang="less">
/* ===== 弹窗外壳 ===== */
.el-dialog.project-settings-modal {
  background: var(--t-bg-base);
  border: 1px solid var(--t-border-subtle);
  border-radius: 16px;
  overflow: hidden;
}
.project-settings-modal .el-dialog__header {
  border-bottom: 1px solid var(--t-border-subtle);
  padding: 16px 20px;
  margin-right: 0;
}
.project-settings-modal .el-dialog__title {
  color: var(--t-text-primary);
  font-weight: 600;
}
.project-settings-modal .el-dialog__body {
  padding: 0;
  height: 400px;
  overflow: hidden;
}
.project-settings-modal .el-dialog__headerbtn .el-dialog__close {
  color: var(--t-text-muted);
}
.project-settings-modal .el-dialog__headerbtn .el-dialog__close:hover {
  color: var(--t-text-secondary);
}
.project-settings-modal .el-dialog__footer {
  border-top: 1px solid var(--t-border-subtle);
  padding: 14px 20px;
}

/* ===== 左右布局 ===== */
.project-settings-modal .settings-layout {
  display: flex;
  height: 100%;
}

/* 左侧 Tabs 栏 */
.project-settings-modal .settings-tabs {
  width: 140px;
  min-width: 140px;
  background: var(--t-bg-base);
  border-right: 1px solid var(--t-border-subtle);
  padding: 8px 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.project-settings-modal .settings-tab-item {
  padding: 10px 20px;
  font-size: 13px;
  color: var(--t-text-muted);
  cursor: pointer;
  transition: all 0.2s;
  border-left: 3px solid transparent;
  user-select: none;
}
.project-settings-modal .settings-tab-item:hover {
  color: var(--t-text-secondary);
  background: var(--t-bg-subtle);
}
.project-settings-modal .settings-tab-item.active {
  color: var(--t-brand-light);
  background: var(--t-brand-subtle);
  border-left-color: var(--t-brand);
}

/* 右侧内容区 */
.project-settings-modal .settings-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 20px 24px;
  background: var(--t-bg-base);
}
.project-settings-modal .settings-content::-webkit-scrollbar {
  width: 5px;
}
.project-settings-modal .settings-content::-webkit-scrollbar-track {
  background: transparent;
}
.project-settings-modal .settings-content::-webkit-scrollbar-thumb {
  background: var(--t-border-strong);
  border-radius: 3px;
}
.project-settings-modal .settings-content::-webkit-scrollbar-thumb:hover {
  background: rgba(255,255,255,0.18);
}

.project-settings-modal .settings-pane {
  min-height: 0;
}

/* ===== 表单元素 ===== */
.project-settings-modal .el-form-item__label {
  color: var(--t-text-secondary);
  font-size: 13px;
}
.project-settings-modal .el-input__wrapper {
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  box-shadow: none;
  border-radius: 10px;
}
.project-settings-modal .el-input__wrapper:hover {
  border-color: var(--t-border-strong);
}
.project-settings-modal .el-input__wrapper.is-focus {
  border-color: var(--t-brand);
  box-shadow: 0 0 0 3px var(--t-brand-subtle);
}
.project-settings-modal .el-input__inner {
  color: var(--t-text-primary);
}
.project-settings-modal .el-input__inner::placeholder {
  color: var(--t-text-muted);
}
.project-settings-modal .el-textarea__inner {
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  color: var(--t-text-primary);
  border-radius: 10px;
  box-shadow: none;
}
.project-settings-modal .el-textarea__inner:focus {
  border-color: var(--t-brand);
  box-shadow: 0 0 0 3px var(--t-brand-subtle);
}
.project-settings-modal .el-textarea__inner::placeholder {
  color: var(--t-text-muted);
}
.project-settings-modal .el-select .el-select__wrapper {
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  box-shadow: none;
  border-radius: 10px;
}

/* ===== 按钮 ===== */
.project-settings-modal .el-button--primary {
  background: var(--t-brand-gradient);
  border: none;
  border-radius: 10px;
}
.project-settings-modal .el-button--primary:hover {
  opacity: 0.9;
}
.project-settings-modal .el-button--default {
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  color: var(--t-text-secondary);
  border-radius: 10px;
}
.project-settings-modal .el-button--default:hover {
  border-color: var(--t-border-strong);
  color: var(--t-text-primary);
}

/* ===== 内嵌 Tabs（账号登录/Token直连） ===== */
.project-settings-modal .connect-mode-tabs {
  margin-bottom: 8px;
}
.project-settings-modal .el-tabs__item {
  color: var(--t-text-muted);
}
.project-settings-modal .el-tabs__item.is-active {
  color: var(--t-brand-light);
}
.project-settings-modal .el-tabs__active-bar {
  background: var(--t-brand-gradient);
}
.project-settings-modal .el-tabs__nav-wrap::after {
  background-color: var(--t-border-subtle);
}

/* ===== Alert ===== */
.project-settings-modal .el-alert--info {
  background: var(--t-brand-subtle);
  border: 1px solid var(--t-brand-subtle);
}
.project-settings-modal .el-alert--info .el-alert__description,
.project-settings-modal .el-alert--info .el-alert__title {
  color: var(--t-text-secondary);
}

/* ===== Tag ===== */
.project-settings-modal .el-tag--info {
  background: var(--t-bg-subtle);
  border-color: var(--t-border-subtle);
  color: var(--t-text-secondary);
}
.project-settings-modal .el-tag--success {
  background: rgba(52,211,153,0.1);
  border-color: rgba(52,211,153,0.2);
  color: var(--t-success);
}

/* ===== 团队成员 ===== */
.project-settings-modal .team-members-section {
  margin-top: 0;
}
.project-settings-modal .add-member-row {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}
.project-settings-modal .members-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--t-text-muted);
  font-size: 13px;
  padding: 8px 0;
}
.project-settings-modal .members-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.project-settings-modal .member-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  gap: 8px;
  transition: border-color 0.2s;
}
.project-settings-modal .member-item:hover {
  border-color: var(--t-border-strong);
}
.project-settings-modal .member-name {
  color: var(--t-text-primary);
  font-size: 13px;
}
.project-settings-modal .member-role-tag {
  flex-shrink: 0;
}
.project-settings-modal .no-members {
  color: var(--t-text-muted);
  font-size: 13px;
  text-align: center;
  padding: 24px 0;
}
</style>

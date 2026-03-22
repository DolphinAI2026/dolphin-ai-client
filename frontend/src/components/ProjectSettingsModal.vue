<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '项目设置' : '新建项目'"
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
            :class="{ active: activeTab === 'platform' }"
            @click="activeTab = 'platform'"
          >
            平台环境
          </div>
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
            <el-form-item label="项目名称" required>
              <el-input v-model="form.name" placeholder="例如：劳务管理系统" />
            </el-form-item>
            <el-form-item label="项目描述">
              <el-input v-model="form.description" type="textarea" :rows="3" placeholder="简要描述项目用途" />
            </el-form-item>
          </el-form>
        </div>

        <!-- 平台环境 -->
        <div v-if="isEdit" v-show="activeTab === 'platform'" class="settings-pane">
          <el-form :model="form" label-position="top" size="default">
            <el-form-item label="平台地址">
              <el-input v-model="form.platform_url" placeholder="https://your-apaas.com/backend/" />
            </el-form-item>
            <el-form-item label="租户ID">
              <el-input v-model="form.platform_tenant_id" placeholder="平台租户ID" />
            </el-form-item>

            <el-tabs v-model="connectMode" class="connect-mode-tabs">
              <el-tab-pane label="账号登录" name="login" />
              <el-tab-pane label="Token直连" name="token" />
            </el-tabs>

            <template v-if="connectMode === 'login'">
              <el-form-item label="用户名（手机号/邮箱）">
                <el-input v-model="loginForm.username" placeholder="请输入登录账号" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="loginForm.password" type="password" show-password placeholder="请输入密码" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="connecting" @click="handleConnect" :disabled="!canConnect">
                  登录并连接平台
                </el-button>
                <el-tag v-if="form.platform_connected" type="success" size="small" style="margin-left: 8px">已连接</el-tag>
                <el-tag v-else type="info" size="small" style="margin-left: 8px">未连接</el-tag>
              </el-form-item>
            </template>

            <template v-else>
              <el-form-item label="Token">
                <el-input v-model="tokenForm.token" type="textarea" :rows="3" placeholder="从浏览器F12复制xdaptoken值" />
              </el-form-item>
              <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px">
                <template #title>
                  <span style="font-size: 12px">登录aPaaS平台 -> F12 -> Network -> 复制请求头中的 xdaptoken 值</span>
                </template>
              </el-alert>
            </template>

            <!-- 应用选择 -->
            <el-form-item label="关联应用">
              <el-select
                v-model="form.platform_app_id"
                placeholder="请先连接平台后选择应用"
                :disabled="!form.platform_connected"
                :loading="loadingApps"
                filterable
                style="width: 100%"
                @change="handleAppSelect"
              >
                <el-option
                  v-for="app in platformApps"
                  :key="app.app_id"
                  :label="`${app.app_name}（${app.app_code}）`"
                  :value="app.app_id"
                />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <!-- 团队成员 -->
        <div v-if="isEdit" v-show="activeTab === 'team'" class="settings-pane">
          <div class="team-members-section">
            <!-- 添加成员 -->
            <div class="add-member-row">
              <el-input
                v-model="newMemberUsername"
                placeholder="输入用户名添加成员"
                size="small"
                style="flex: 1"
                @keyup.enter="handleAddMember"
              />
              <el-select v-model="newMemberRole" size="small" style="width: 100px; margin-left: 8px">
                <el-option label="管理员" value="admin" />
                <el-option label="成员" value="member" />
              </el-select>
              <el-button
                type="primary"
                size="small"
                :loading="addingMember"
                style="margin-left: 8px"
                @click="handleAddMember"
              >
                添加
              </el-button>
            </div>

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
                    size="small"
                    style="width: 90px; margin-left: auto"
                    @change="(val: string) => handleUpdateRole(member, val)"
                  >
                    <el-option label="管理员" value="admin" />
                    <el-option label="成员" value="member" />
                  </el-select>
                  <el-button
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
      <el-button type="primary" :loading="saving" @click="handleSave">
        {{ isEdit ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, Close } from '@element-plus/icons-vue'
import { projectsApi } from '@/api/projects'
import type { Project, PlatformApp, ProjectMember } from '@/api/projects'

const props = defineProps<{
  project?: Project | null
}>()

const emit = defineEmits<{
  saved: [project: Project]
}>()

const visible = defineModel<boolean>({ default: false })

const isEdit = computed(() => !!props.project?.id)
const activeTab = ref('basic')

const form = reactive({
  name: '',
  description: '',
  platform_url: '',
  platform_tenant_id: '',
  platform_app_id: '',
  platform_app_name: '',
  platform_connected: false,
})

const connectMode = ref('login')
const loginForm = reactive({ username: '', password: '' })
const tokenForm = reactive({ token: '' })
const connecting = ref(false)
const saving = ref(false)
const loadingApps = ref(false)
const platformApps = ref<PlatformApp[]>([])

// 团队成员
const members = ref<ProjectMember[]>([])
const loadingMembers = ref(false)
const addingMember = ref(false)
const newMemberUsername = ref('')
const newMemberRole = ref('member')

const canConnect = computed(() => {
  return form.platform_url && form.platform_tenant_id && loginForm.username && loginForm.password
})

// Watch for project changes to populate form
watch(() => props.project, (p) => {
  if (p) {
    form.name = p.name || ''
    form.description = p.description || ''
    form.platform_url = p.platform_url || ''
    form.platform_tenant_id = p.platform_tenant_id || ''
    form.platform_app_id = p.platform_app_id || ''
    form.platform_app_name = p.platform_app_name || ''
    form.platform_connected = p.platform_connected || false
    loginForm.username = p.platform_username || ''
    loginForm.password = ''
    tokenForm.token = ''
    // 已连接平台时自动加载应用列表
    if (p.platform_connected) {
      fetchPlatformApps()
    }
    // 加载成员列表
    fetchMembers()
  } else {
    form.name = ''
    form.description = ''
    form.platform_url = ''
    form.platform_tenant_id = ''
    form.platform_app_id = ''
    form.platform_app_name = ''
    form.platform_connected = false
    loginForm.username = ''
    loginForm.password = ''
    tokenForm.token = ''
    platformApps.value = []
    members.value = []
    newMemberUsername.value = ''
    newMemberRole.value = 'member'
  }
  // Reset to basic tab when dialog opens
  activeTab.value = 'basic'
}, { immediate: true })

async function fetchPlatformApps() {
  if (!props.project?.id || !form.platform_connected) return
  loadingApps.value = true
  try {
    platformApps.value = await projectsApi.listPlatformApps(props.project.id)
  } catch (e: any) {
    console.error('获取应用列表失败:', e)
    platformApps.value = []
  } finally {
    loadingApps.value = false
  }
}

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

async function handleAddMember() {
  if (!props.project?.id || !newMemberUsername.value.trim()) return
  addingMember.value = true
  try {
    const member = await projectsApi.addMember(props.project.id, {
      username: newMemberUsername.value.trim(),
      role: newMemberRole.value,
    })
    members.value.push(member)
    newMemberUsername.value = ''
    newMemberRole.value = 'member'
    ElMessage.success('成员已添加')
  } catch (e: any) {
    ElMessage.error(e.message || '添加成员失败')
  } finally {
    addingMember.value = false
  }
}

async function handleRemoveMember(member: ProjectMember) {
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
  if (!props.project?.id) return
  try {
    await projectsApi.updateMemberRole(props.project.id, member.id, newRole)
    member.role = newRole as ProjectMember['role']
    ElMessage.success('角色已更新')
  } catch (e: any) {
    ElMessage.error(e.message || '更新角色失败')
  }
}

function handleAppSelect(appId: string) {
  const app = platformApps.value.find(a => a.app_id === appId)
  if (app) {
    form.platform_app_name = app.app_name
  }
}

async function handleConnect() {
  if (!props.project?.id) return
  connecting.value = true
  try {
    const updated = await projectsApi.connect(props.project.id, {
      username: loginForm.username,
      password: loginForm.password,
      base_url: form.platform_url,
      tenant_id: form.platform_tenant_id,
    })
    form.platform_connected = true
    ElMessage.success('平台连接成功')
    emit('saved', updated)
    // 连接成功后自动加载应用列表
    await fetchPlatformApps()
  } catch (e: any) {
    ElMessage.error(e.message || '连接失败')
  } finally {
    connecting.value = false
  }
}

async function handleSave() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入项目名称')
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
        platform_url: form.platform_url,
        platform_tenant_id: form.platform_tenant_id,
        platform_app_id: form.platform_app_id,
        platform_app_name: form.platform_app_name,
      }
      // If token mode, include token
      if (connectMode.value === 'token' && tokenForm.token.trim()) {
        updateData.platform_token = tokenForm.token.trim()
      }
      if (loginForm.username) {
        updateData.platform_username = loginForm.username
      }
      result = await projectsApi.update(props.project.id, updateData)
    } else {
      // Create new project
      result = await projectsApi.create({
        name: form.name,
        description: form.description,
      })
    }
    ElMessage.success(isEdit.value ? '项目已保存' : '项目已创建')
    emit('saved', result)
    visible.value = false
  } catch (e: any) {
    ElMessage.error(e.message || '操作失败')
  } finally {
    saving.value = false
  }
}
</script>

<style>
/* ===== 弹窗外壳 ===== */
.el-dialog.project-settings-modal {
  background: #111;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px;
  overflow: hidden;
}
.project-settings-modal .el-dialog__header {
  border-bottom: 1px solid rgba(255,255,255,0.06);
  padding: 16px 20px;
  margin-right: 0;
}
.project-settings-modal .el-dialog__title {
  color: rgba(255,255,255,0.9);
  font-weight: 600;
}
.project-settings-modal .el-dialog__body {
  padding: 0;
  height: 400px;
  overflow: hidden;
}
.project-settings-modal .el-dialog__headerbtn .el-dialog__close {
  color: rgba(255,255,255,0.4);
}
.project-settings-modal .el-dialog__headerbtn .el-dialog__close:hover {
  color: rgba(255,255,255,0.7);
}
.project-settings-modal .el-dialog__footer {
  border-top: 1px solid rgba(255,255,255,0.06);
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
  background: #0a0a0a;
  border-right: 1px solid rgba(255,255,255,0.06);
  padding: 8px 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.project-settings-modal .settings-tab-item {
  padding: 10px 20px;
  font-size: 13px;
  color: rgba(255,255,255,0.4);
  cursor: pointer;
  transition: all 0.2s;
  border-left: 3px solid transparent;
  user-select: none;
}
.project-settings-modal .settings-tab-item:hover {
  color: rgba(255,255,255,0.65);
  background: rgba(255,255,255,0.03);
}
.project-settings-modal .settings-tab-item.active {
  color: #a78bfa;
  background: rgba(124,58,237,0.08);
  border-left-color: #7c3aed;
}

/* 右侧内容区 */
.project-settings-modal .settings-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 20px 24px;
  background: #111;
}
.project-settings-modal .settings-content::-webkit-scrollbar {
  width: 5px;
}
.project-settings-modal .settings-content::-webkit-scrollbar-track {
  background: transparent;
}
.project-settings-modal .settings-content::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.1);
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
  color: rgba(255,255,255,0.55);
  font-size: 13px;
}
.project-settings-modal .el-input__wrapper {
  background: #161622;
  border: 1px solid rgba(255,255,255,0.08);
  box-shadow: none;
  border-radius: 10px;
}
.project-settings-modal .el-input__wrapper:hover {
  border-color: rgba(255,255,255,0.15);
}
.project-settings-modal .el-input__wrapper.is-focus {
  border-color: #7c3aed;
  box-shadow: 0 0 0 3px rgba(124,58,237,0.15);
}
.project-settings-modal .el-input__inner {
  color: rgba(255,255,255,0.9);
}
.project-settings-modal .el-input__inner::placeholder {
  color: rgba(255,255,255,0.25);
}
.project-settings-modal .el-textarea__inner {
  background: #161622;
  border: 1px solid rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.9);
  border-radius: 10px;
  box-shadow: none;
}
.project-settings-modal .el-textarea__inner:focus {
  border-color: #7c3aed;
  box-shadow: 0 0 0 3px rgba(124,58,237,0.15);
}
.project-settings-modal .el-textarea__inner::placeholder {
  color: rgba(255,255,255,0.25);
}
.project-settings-modal .el-select .el-select__wrapper {
  background: #161622;
  border: 1px solid rgba(255,255,255,0.08);
  box-shadow: none;
  border-radius: 10px;
}

/* ===== 按钮 ===== */
.project-settings-modal .el-button--primary {
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  border: none;
  border-radius: 10px;
}
.project-settings-modal .el-button--primary:hover {
  opacity: 0.9;
}
.project-settings-modal .el-button--default {
  background: #161622;
  border: 1px solid rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.7);
  border-radius: 10px;
}
.project-settings-modal .el-button--default:hover {
  border-color: rgba(255,255,255,0.18);
  color: rgba(255,255,255,0.85);
}

/* ===== 内嵌 Tabs（账号登录/Token直连） ===== */
.project-settings-modal .connect-mode-tabs {
  margin-bottom: 8px;
}
.project-settings-modal .el-tabs__item {
  color: rgba(255,255,255,0.45);
}
.project-settings-modal .el-tabs__item.is-active {
  color: #a78bfa;
}
.project-settings-modal .el-tabs__active-bar {
  background: linear-gradient(135deg, #7c3aed, #6366f1);
}
.project-settings-modal .el-tabs__nav-wrap::after {
  background-color: rgba(255,255,255,0.06);
}

/* ===== Alert ===== */
.project-settings-modal .el-alert--info {
  background: rgba(124,58,237,0.08);
  border: 1px solid rgba(124,58,237,0.15);
}
.project-settings-modal .el-alert--info .el-alert__description,
.project-settings-modal .el-alert--info .el-alert__title {
  color: rgba(255,255,255,0.6);
}

/* ===== Tag ===== */
.project-settings-modal .el-tag--info {
  background: rgba(255,255,255,0.06);
  border-color: rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.5);
}
.project-settings-modal .el-tag--success {
  background: rgba(52,211,153,0.1);
  border-color: rgba(52,211,153,0.2);
  color: #34d399;
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
  color: rgba(255,255,255,0.4);
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
  background: #161622;
  border: 1px solid rgba(255,255,255,0.06);
  gap: 8px;
  transition: border-color 0.2s;
}
.project-settings-modal .member-item:hover {
  border-color: rgba(255,255,255,0.1);
}
.project-settings-modal .member-name {
  color: rgba(255,255,255,0.85);
  font-size: 13px;
}
.project-settings-modal .member-role-tag {
  flex-shrink: 0;
}
.project-settings-modal .no-members {
  color: rgba(255,255,255,0.3);
  font-size: 13px;
  text-align: center;
  padding: 24px 0;
}
</style>

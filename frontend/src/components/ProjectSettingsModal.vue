<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '项目设置' : '新建项目'"
    width="520px"
    :close-on-click-modal="false"
    class="project-settings-modal"
  >
    <el-form :model="form" label-position="top" size="default">
      <!-- 基本信息 -->
      <el-form-item label="项目名称" required>
        <el-input v-model="form.name" placeholder="例如：劳务管理系统" />
      </el-form-item>
      <el-form-item label="项目描述">
        <el-input v-model="form.description" type="textarea" :rows="2" placeholder="简要描述项目用途" />
      </el-form-item>

      <!-- 平台环境配置（仅编辑模式显示） -->
      <template v-if="isEdit">
        <el-divider content-position="left">平台环境配置</el-divider>

        <el-form-item label="平台地址">
          <el-input v-model="form.platform_url" placeholder="https://your-apaas.com/backend/" />
        </el-form-item>
        <el-form-item label="租户ID">
          <el-input v-model="form.platform_tenant_id" placeholder="平台租户ID" />
        </el-form-item>

        <el-tabs v-model="connectMode" style="margin-bottom: 8px">
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

        <!-- 团队成员 -->
        <el-divider content-position="left">团队成员</el-divider>

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
              :disabled="!newMemberUsername.trim()"
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
      </template>
    </el-form>

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

<style scoped>
.project-settings-modal :deep(.el-dialog) {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
}
.project-settings-modal :deep(.el-dialog__header) {
  border-bottom: 1px solid #2a2a2a;
}
.project-settings-modal :deep(.el-dialog__title) {
  color: #e0e0e0;
}
.project-settings-modal :deep(.el-form-item__label) {
  color: #aaa;
}
.project-settings-modal :deep(.el-divider__text) {
  color: #888;
  background: #1a1a1a;
}

/* 团队成员 */
.team-members-section {
  margin-top: 4px;
}
.add-member-row {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}
.members-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #888;
  font-size: 13px;
  padding: 8px 0;
}
.members-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.member-item {
  display: flex;
  align-items: center;
  padding: 6px 8px;
  border-radius: 4px;
  background: #222;
  gap: 8px;
}
.member-name {
  color: #e0e0e0;
  font-size: 13px;
}
.member-role-tag {
  flex-shrink: 0;
}
.no-members {
  color: #666;
  font-size: 13px;
  text-align: center;
  padding: 12px 0;
}
</style>

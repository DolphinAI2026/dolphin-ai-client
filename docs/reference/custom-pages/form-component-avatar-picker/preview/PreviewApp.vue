<template>
  <div id="preview-app">
    <div class="preview-card">
      <div class="preview-title">人员头像组件 - FORM_COMPONENT 预览</div>
      <div class="preview-subtitle">templateType: FORM_COMPONENT | code: FORM_CUSTOM_COMPONENT_AVATAR_PICKER</div>

      <el-divider>编辑态 (Edit Scene)</el-divider>
      <div class="avatar-edit-demo">
        <div class="avatar-picker-edit-body">
          <div class="avatar-picker-edit-list" v-if="selectedUsers.length > 0">
            <div
              class="avatar-picker-edit-item"
              v-for="(user, index) in displayUsers"
              :key="user.userId"
              :title="user.userName"
            >
              <div class="avatar-picker-edit-avatar is-circle" style="width:36px;height:36px;line-height:36px;font-size:14px;">
                <span class="avatar-picker-edit-initial">{{ user.userName.charAt(0) }}</span>
              </div>
              <span class="avatar-picker-edit-name">{{ user.userName }}</span>
              <i class="el-icon-close avatar-picker-edit-remove" @click="removeUser(index)"></i>
            </div>
            <div v-if="overflowCount > 0" class="avatar-picker-edit-item">
              <div class="avatar-picker-edit-avatar avatar-picker-edit-overflow-badge is-circle" style="width:36px;height:36px;line-height:36px;font-size:12px;">
                +{{ overflowCount }}
              </div>
            </div>
          </div>
          <div class="avatar-picker-edit-add is-circle" style="width:36px;height:36px;" @click="openDialog">
            <i class="el-icon-plus"></i>
          </div>
        </div>
      </div>

      <el-divider>只读态 (Read Scene)</el-divider>
      <div class="avatar-read-demo">
        <div class="avatar-picker-edit-list" v-if="selectedUsers.length > 0">
          <div
            class="avatar-picker-edit-item"
            v-for="user in displayUsers"
            :key="'read-' + user.userId"
          >
            <div class="avatar-picker-edit-avatar is-circle" style="width:36px;height:36px;line-height:36px;font-size:14px;">
              <span class="avatar-picker-edit-initial">{{ user.userName.charAt(0) }}</span>
            </div>
            <span class="avatar-picker-edit-name">{{ user.userName }}</span>
          </div>
        </div>
        <span v-else style="color:#909399;">-</span>
      </div>

      <el-divider>列表态 (List Scene)</el-divider>
      <div class="avatar-list-demo">
        <div style="display:flex;align-items:center;gap:4px;" v-if="selectedUsers.length > 0">
          <div
            v-for="user in selectedUsers.slice(0,3)"
            :key="'list-' + user.userId"
            style="width:24px;height:24px;border-radius:50%;background:#e6f0ff;border:1px solid #d9e6ff;display:flex;align-items:center;justify-content:center;color:#409EFF;font-size:11px;font-weight:500;"
          >{{ user.userName.charAt(0) }}</div>
          <span v-if="selectedUsers.length > 3" style="font-size:12px;color:#909399;">+{{ selectedUsers.length - 3 }}</span>
        </div>
        <span v-else style="color:#909399;font-size:12px;">-</span>
      </div>

      <el-divider>当前值</el-divider>
      <pre style="background:#f5f7fa;padding:12px;border-radius:4px;font-size:12px;max-height:200px;overflow:auto;">{{ JSON.stringify(selectedUsers, null, 2) }}</pre>
    </div>

    <!-- 选人对话框 -->
    <el-dialog title="选择人员" :visible.sync="dialogVisible" width="480px" :close-on-click-modal="false">
      <el-input v-model="searchKw" placeholder="搜索人员姓名" size="small" prefix-icon="el-icon-search" clearable style="margin-bottom:12px;" />
      <div style="max-height:300px;overflow-y:auto;border:1px solid #ebeef5;border-radius:4px;">
        <div
          v-for="user in filteredCandidates"
          :key="user.userId"
          style="display:flex;align-items:center;padding:8px 12px;cursor:pointer;transition:background 0.2s;"
          :style="{ background: isSelected(user) ? '#ecf5ff' : '' }"
          @click="toggleUser(user)"
        >
          <div style="width:32px;height:32px;border-radius:50%;background:#e6f0ff;display:flex;align-items:center;justify-content:center;margin-right:10px;color:#409EFF;font-size:14px;font-weight:500;">
            {{ user.userName.charAt(0) }}
          </div>
          <span style="flex:1;font-size:14px;color:#303133;">{{ user.userName }}</span>
          <i v-if="isSelected(user)" class="el-icon-check" style="color:#409EFF;font-size:16px;font-weight:bold;"></i>
        </div>
      </div>
      <span slot="footer">
        <el-button size="small" @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" size="small" @click="confirmSelect">确定</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
const CANDIDATES = [
  { userId: '1', userName: '张三', avatar: '' },
  { userId: '2', userName: '李四', avatar: '' },
  { userId: '3', userName: '王五', avatar: '' },
  { userId: '4', userName: '赵六', avatar: '' },
  { userId: '5', userName: '钱七', avatar: '' },
  { userId: '6', userName: '孙八', avatar: '' },
  { userId: '7', userName: '周九', avatar: '' },
  { userId: '8', userName: '吴十', avatar: '' }
]

export default {
  name: 'PreviewApp',
  data() {
    return {
      selectedUsers: [],
      dialogVisible: false,
      searchKw: '',
      tempSelected: [],
      maxDisplay: 5
    }
  },
  computed: {
    displayUsers() { return this.selectedUsers.slice(0, this.maxDisplay) },
    overflowCount() { return Math.max(0, this.selectedUsers.length - this.maxDisplay) },
    filteredCandidates() {
      if (!this.searchKw) return CANDIDATES
      const kw = this.searchKw.toLowerCase()
      return CANDIDATES.filter(u => u.userName.toLowerCase().includes(kw))
    }
  },
  methods: {
    removeUser(index) { this.selectedUsers.splice(index, 1) },
    openDialog() {
      this.searchKw = ''
      this.tempSelected = [...this.selectedUsers]
      this.dialogVisible = true
    },
    isSelected(user) { return this.tempSelected.some(u => u.userId === user.userId) },
    toggleUser(user) {
      const idx = this.tempSelected.findIndex(u => u.userId === user.userId)
      if (idx >= 0) { this.tempSelected.splice(idx, 1) } else { this.tempSelected.push({ ...user }) }
    },
    confirmSelect() {
      this.selectedUsers = [...this.tempSelected]
      this.dialogVisible = false
    }
  }
}
</script>

<style>
.preview-card { background: #fff; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); padding: 24px; }
.preview-title { font-size: 18px; font-weight: 600; color: #303133; margin-bottom: 16px; }
.preview-subtitle { font-size: 14px; color: #909399; margin-bottom: 12px; }
.avatar-picker-edit-body { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 8px; }
.avatar-picker-edit-list { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 8px; }
.avatar-picker-edit-item { position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; }
.avatar-picker-edit-item:hover .avatar-picker-edit-remove { display: flex !important; }
.avatar-picker-edit-avatar { overflow: hidden; display: flex; align-items: center; justify-content: center; background: #e6f0ff; border: 1px solid #d9e6ff; color: #409EFF; font-weight: 500; }
.avatar-picker-edit-avatar.is-circle { border-radius: 50%; }
.avatar-picker-edit-avatar.is-square { border-radius: 4px; }
.avatar-picker-edit-initial { user-select: none; }
.avatar-picker-edit-name { font-size: 12px; color: #606266; max-width: 60px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: center; }
.avatar-picker-edit-remove { display: none; position: absolute; top: -4px; right: -4px; width: 16px; height: 16px; border-radius: 50%; background: #f56c6c; color: #fff; font-size: 10px; align-items: center; justify-content: center; cursor: pointer; z-index: 1; }
.avatar-picker-edit-overflow-badge { background: #f0f2f5 !important; color: #909399 !important; border-color: #e4e7ed !important; font-size: 12px !important; }
.avatar-picker-edit-add { border: 1px dashed #c0c4cc; display: flex; align-items: center; justify-content: center; color: #c0c4cc; cursor: pointer; transition: all 0.2s; }
.avatar-picker-edit-add.is-circle { border-radius: 50%; }
.avatar-picker-edit-add:hover { border-color: #409EFF; color: #409EFF; }
</style>

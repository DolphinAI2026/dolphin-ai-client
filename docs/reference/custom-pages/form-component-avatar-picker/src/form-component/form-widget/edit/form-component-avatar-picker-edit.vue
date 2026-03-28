<template>
  <div class="form-widget form-component-avatar-picker-edit">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :titleDescription="widget.titleDescription"
      :renderScene="renderScene"
      :processTitle="widget.processTitle"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
      :webFormSettings="webFormSettings"
    >
      <div class="avatar-picker-edit-body">
        <!-- 已选人员头像列表 -->
        <div class="avatar-picker-edit-list" v-if="selectedUsers.length > 0">
          <div
            class="avatar-picker-edit-item"
            v-for="(user, index) in displayUsers"
            :key="user.userId || index"
            :title="user.userName || ''"
          >
            <div
              class="avatar-picker-edit-avatar"
              :class="avatarShapeClass"
              :style="avatarSizeStyle"
            >
              <img
                v-if="user.avatar"
                :src="user.avatar"
                :alt="user.userName"
                class="avatar-picker-edit-img"
              />
              <span v-else class="avatar-picker-edit-initial" :style="initialFontStyle">
                {{ getInitial(user.userName) }}
              </span>
            </div>
            <span v-if="config.showName !== false" class="avatar-picker-edit-name">
              {{ user.userName || '-' }}
            </span>
            <i
              class="el-icon-close avatar-picker-edit-remove"
              @click="removeUser(index)"
            ></i>
          </div>
          <!-- 超出数量提示 -->
          <div v-if="overflowCount > 0" class="avatar-picker-edit-overflow">
            <div
              class="avatar-picker-edit-avatar avatar-picker-edit-overflow-badge"
              :class="avatarShapeClass"
              :style="avatarSizeStyle"
            >
              +{{ overflowCount }}
            </div>
          </div>
        </div>

        <!-- 添加按钮 -->
        <div
          class="avatar-picker-edit-add"
          :class="avatarShapeClass"
          :style="avatarSizeStyle"
          @click="openSelector"
        >
          <i class="el-icon-plus"></i>
        </div>
      </div>

      <!-- 人员选择对话框 -->
      <el-dialog
        title="选择人员"
        :visible.sync="dialogVisible"
        width="480px"
        append-to-body
        :close-on-click-modal="false"
      >
        <div class="avatar-picker-dialog-body">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索人员姓名"
            size="small"
            prefix-icon="el-icon-search"
            clearable
            @input="onSearchInput"
            style="margin-bottom: 12px"
          />
          <div class="avatar-picker-dialog-list">
            <div
              v-for="user in filteredCandidates"
              :key="user.userId"
              class="avatar-picker-dialog-item"
              :class="{ 'is-selected': isSelected(user) }"
              @click="toggleUser(user)"
            >
              <div class="avatar-picker-dialog-avatar">
                <img v-if="user.avatar" :src="user.avatar" :alt="user.userName" />
                <span v-else class="avatar-picker-dialog-initial">
                  {{ getInitial(user.userName) }}
                </span>
              </div>
              <span class="avatar-picker-dialog-name">{{ user.userName }}</span>
              <i v-if="isSelected(user)" class="el-icon-check avatar-picker-dialog-check"></i>
            </div>
            <div v-if="filteredCandidates.length === 0" class="avatar-picker-dialog-empty">
              暂无数据
            </div>
          </div>
        </div>
        <span slot="footer" class="dialog-footer">
          <el-button size="small" @click="dialogVisible = false">取 消</el-button>
          <el-button type="primary" size="small" @click="confirmSelect">确 定</el-button>
        </span>
      </el-dialog>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

// 颜色池用于生成姓名首字母的背景色
const COLORS = [
  '#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399',
  '#1890FF', '#52C41A', '#FAAD14', '#FF4D4F', '#722ED1'
]

function getColorByName(name) {
  if (!name) return COLORS[0]
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return COLORS[Math.abs(hash) % COLORS.length]
}

export default {
  name: 'FormComponentAvatarPickerEdit',
  mixins: [FormWidgetMixin],
  data() {
    return {
      dialogVisible: false,
      searchKeyword: '',
      tempSelected: [],
      // 模拟候选人列表 —— 实际可通过平台API获取
      candidateUsers: [
        { userId: '1', userName: '张三', avatar: '' },
        { userId: '2', userName: '李四', avatar: '' },
        { userId: '3', userName: '王五', avatar: '' },
        { userId: '4', userName: '赵六', avatar: '' },
        { userId: '5', userName: '钱七', avatar: '' },
        { userId: '6', userName: '孙八', avatar: '' },
        { userId: '7', userName: '周九', avatar: '' },
        { userId: '8', userName: '吴十', avatar: '' }
      ]
    }
  },
  computed: {
    config() {
      return (this.widget && this.widget.customComponentConfig) || {}
    },
    selectedUsers() {
      if (!this.formValue) return []
      if (typeof this.formValue === 'string') {
        try {
          return JSON.parse(this.formValue) || []
        } catch (e) {
          return []
        }
      }
      if (Array.isArray(this.formValue)) return this.formValue
      return []
    },
    maxDisplay() {
      return this.config.maxDisplay || 5
    },
    displayUsers() {
      return this.selectedUsers.slice(0, this.maxDisplay)
    },
    overflowCount() {
      return Math.max(0, this.selectedUsers.length - this.maxDisplay)
    },
    avatarShapeClass() {
      return this.config.avatarShape === 'square' ? 'is-square' : 'is-circle'
    },
    avatarSizeStyle() {
      const size = this.config.avatarSize || 36
      return {
        width: size + 'px',
        height: size + 'px',
        lineHeight: size + 'px',
        fontSize: Math.max(12, Math.floor(size * 0.4)) + 'px'
      }
    },
    initialFontStyle() {
      const size = this.config.avatarSize || 36
      return { fontSize: Math.max(12, Math.floor(size * 0.4)) + 'px' }
    },
    isSingle() {
      return this.config.selectMode === 'single'
    },
    filteredCandidates() {
      if (!this.searchKeyword) return this.candidateUsers
      const kw = this.searchKeyword.toLowerCase()
      return this.candidateUsers.filter(u =>
        (u.userName || '').toLowerCase().includes(kw)
      )
    }
  },
  methods: {
    getInitial(name) {
      return name ? name.charAt(0) : '?'
    },
    getColor(name) {
      return getColorByName(name)
    },
    removeUser(index) {
      const list = [...this.selectedUsers]
      list.splice(index, 1)
      this.formValue = JSON.stringify(list)
    },
    openSelector() {
      this.searchKeyword = ''
      this.tempSelected = [...this.selectedUsers]
      this.dialogVisible = true
    },
    isSelected(user) {
      return this.tempSelected.some(u => u.userId === user.userId)
    },
    toggleUser(user) {
      const idx = this.tempSelected.findIndex(u => u.userId === user.userId)
      if (idx >= 0) {
        this.tempSelected.splice(idx, 1)
      } else {
        if (this.isSingle) {
          this.tempSelected = [{ ...user }]
        } else {
          this.tempSelected.push({ ...user })
        }
      }
    },
    confirmSelect() {
      this.formValue = JSON.stringify(this.tempSelected)
      this.dialogVisible = false
    },
    onSearchInput() {
      // debounce handled by el-input
    }
  }
}
</script>

<style lang="scss">
.form-component-avatar-picker-edit {
  .avatar-picker-edit-body {
    display: flex;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 8px;
  }

  .avatar-picker-edit-list {
    display: flex;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 8px;
  }

  .avatar-picker-edit-item {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;

    &:hover .avatar-picker-edit-remove {
      display: flex;
    }
  }

  .avatar-picker-edit-avatar {
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #e6f0ff;
    border: 1px solid #d9e6ff;
    color: #409EFF;
    font-weight: 500;

    &.is-circle { border-radius: 50%; }
    &.is-square { border-radius: 4px; }
  }

  .avatar-picker-edit-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .avatar-picker-edit-initial {
    user-select: none;
  }

  .avatar-picker-edit-name {
    font-size: 12px;
    color: #606266;
    max-width: 60px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: center;
  }

  .avatar-picker-edit-remove {
    display: none;
    position: absolute;
    top: -4px;
    right: -4px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #f56c6c;
    color: #fff;
    font-size: 10px;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    z-index: 1;
  }

  .avatar-picker-edit-overflow-badge {
    background: #f0f2f5 !important;
    color: #909399 !important;
    border-color: #e4e7ed !important;
    font-size: 12px !important;
    font-weight: 500;
  }

  .avatar-picker-edit-add {
    border: 1px dashed #c0c4cc;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #c0c4cc;
    cursor: pointer;
    transition: all 0.2s;

    &.is-circle { border-radius: 50%; }
    &.is-square { border-radius: 4px; }

    &:hover {
      border-color: #409EFF;
      color: #409EFF;
    }
  }
}

// 对话框样式
.avatar-picker-dialog-body {
  .avatar-picker-dialog-list {
    max-height: 300px;
    overflow-y: auto;
    border: 1px solid #ebeef5;
    border-radius: 4px;
  }

  .avatar-picker-dialog-item {
    display: flex;
    align-items: center;
    padding: 8px 12px;
    cursor: pointer;
    transition: background 0.2s;

    &:hover {
      background: #f5f7fa;
    }

    &.is-selected {
      background: #ecf5ff;
    }
  }

  .avatar-picker-dialog-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #e6f0ff;
    margin-right: 10px;
    flex-shrink: 0;

    img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
  }

  .avatar-picker-dialog-initial {
    color: #409EFF;
    font-size: 14px;
    font-weight: 500;
  }

  .avatar-picker-dialog-name {
    flex: 1;
    font-size: 14px;
    color: #303133;
  }

  .avatar-picker-dialog-check {
    color: #409EFF;
    font-size: 16px;
    font-weight: bold;
  }

  .avatar-picker-dialog-empty {
    padding: 24px;
    text-align: center;
    color: #909399;
    font-size: 14px;
  }
}
</style>

<template>
  <div class="apaas-custom-avatar-picker">

    <!-- 顶部搜索区 -->
    <div class="search-area">
      <el-input
        v-model="keyword"
        placeholder="搜索姓名、工号或部门"
        prefix-icon="el-icon-search"
        size="small"
        clearable
        @keyup.enter.native="handleQuery"
        @clear="handleQuery"
      />
      <el-select v-model="deptFilter" placeholder="全部部门" size="small" clearable @change="handleQuery">
        <el-option v-for="d in deptOptions" :key="d.value" :label="d.label" :value="d.value" />
      </el-select>
      <el-button type="primary" size="small" icon="el-icon-search" @click="handleQuery">查询</el-button>
      <el-button size="small" icon="el-icon-refresh" @click="handleReset">重置</el-button>
    </div>

    <!-- 已选提示条 -->
    <div class="selected-bar">
      <span class="selected-bar-title">
        已选人员
        <span v-if="selectedUsers.length" class="selected-badge">{{ selectedUsers.length }}</span>
      </span>
      <template v-if="selectedUsers.length === 0">
        <span class="selected-bar-empty">暂未选择</span>
      </template>
      <template v-else>
        <div class="selected-bar-avatars">
          <div
            v-for="user in selectedUsers"
            :key="user.id"
            class="selected-avatar-item"
            :title="user.name"
          >
            <div class="mini-avatar" :style="{ background: getAvatarColor(user.name) }">
              <img v-if="user.avatar" :src="user.avatar" class="mini-avatar-img" />
              <span v-else class="mini-avatar-text">{{ getInitial(user.name) }}</span>
            </div>
            <span class="mini-avatar-name">{{ user.name }}</span>
            <span class="mini-avatar-close" @click="removeSelected(user)">&#215;</span>
          </div>
        </div>
        <span class="bar-clear" @click="clearAllSelected">清空</span>
      </template>
    </div>

    <!-- 人员卡片网格 -->
    <div class="avatar-grid-wrapper">
      <div v-if="loading" class="loading-overlay">
        <i class="el-icon-loading"></i> 加载中...
      </div>
      <div v-else-if="userList.length === 0" class="empty-state">
        <i class="el-icon-user"></i>
        <p>暂无人员数据</p>
      </div>
      <div v-else class="avatar-grid">
        <div
          v-for="user in userList"
          :key="user.id"
          class="avatar-card"
          :class="{ 'avatar-card-selected': isSelected(user) }"
          @click="toggleSelect(user)"
        >
          <!-- 选中角标 -->
          <div v-if="isSelected(user)" class="card-check">
            <i class="el-icon-check"></i>
          </div>

          <!-- 头像 -->
          <div class="avatar-circle" :style="{ background: getAvatarColor(user.name) }">
            <img v-if="user.avatar" :src="user.avatar" class="avatar-img" />
            <span v-else class="avatar-initial">{{ getInitial(user.name) }}</span>
          </div>

          <!-- 信息 -->
          <div class="card-info">
            <div class="card-name">{{ user.name }}</div>
            <div class="card-meta">{{ user.employeeNo }}</div>
            <div class="card-dept">{{ user.department }}</div>
            <div v-if="user.position" class="card-position">{{ user.position }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div class="pagination-area">
      <el-pagination
        :current-page="pagination.currentPage"
        :page-size="pagination.pageSize"
        :total="pagination.total"
        :page-sizes="[12, 24, 48]"
        layout="total, sizes, prev, pager, next"
        @size-change="onSizeChange"
        @current-change="onPageChange"
      />
    </div>

  </div>
</template>

<script>
import Api from '../api'

// 头像颜色调色板
const AVATAR_COLORS = [
  '#1890ff', '#52c41a', '#faad14', '#f5222d', '#722ed1',
  '#13c2c2', '#eb2f96', '#fa8c16', '#2f54eb', '#a0d911',
  '#1da57a', '#9254de', '#f759ab', '#597ef7', '#36cfc9',
]

export default {
  name: 'ApaasCustomAvatarPicker',

  data() {
    return {
      keyword: '',
      deptFilter: '',
      deptOptions: [],
      loading: false,
      userList: [],
      selectedUsers: [],
      pagination: {
        currentPage: 1,
        pageSize: 12,
        total: 0,
      },
    }
  },

  created() {
    this.loadUsers()
  },

  methods: {
    // ══════════════════════════════════════
    // 数据加载
    // ══════════════════════════════════════

    loadUsers() {
      this.loading = true
      this.$request({
        ...Api.QUERY_USERS,
        params: {
          keyword: this.keyword,
          department: this.deptFilter,
          page: this.pagination.currentPage,
          pageSize: this.pagination.pageSize,
        },
      })
        .asyncThen((resp) => {
          this.loading = false
          if (resp.code === 0 && resp.data) {
            this.userList = resp.data.list || []
            this.pagination.total = resp.data.total || 0
            // 首次加载时提取部门列表
            if (this.deptOptions.length === 0 && resp.data.departments) {
              this.deptOptions = resp.data.departments.map(d => ({ label: d, value: d }))
            }
          } else {
            this.userList = []
            this.pagination.total = 0
          }
        })
        .asyncErrorCatch((err) => {
          this.loading = false
          console.error('加载人员失败:', err)
        })
    },

    handleQuery() {
      this.pagination.currentPage = 1
      this.loadUsers()
    },

    handleReset() {
      this.keyword = ''
      this.deptFilter = ''
      this.pagination.currentPage = 1
      this.loadUsers()
    },

    onSizeChange(size) {
      this.pagination.pageSize = size
      this.pagination.currentPage = 1
      this.loadUsers()
    },

    onPageChange(page) {
      this.pagination.currentPage = page
      this.loadUsers()
    },

    // ══════════════════════════════════════
    // 选择逻辑（跨页保持）
    // ══════════════════════════════════════

    isSelected(user) {
      return this.selectedUsers.some(u => u.id === user.id)
    },

    toggleSelect(user) {
      if (this.isSelected(user)) {
        this.selectedUsers = this.selectedUsers.filter(u => u.id !== user.id)
      } else {
        this.selectedUsers.push({ ...user })
      }
    },

    removeSelected(user) {
      this.selectedUsers = this.selectedUsers.filter(u => u.id !== user.id)
    },

    clearAllSelected() {
      this.selectedUsers = []
    },

    // ══════════════════════════════════════
    // 弹窗调用接口（x-lov 场景）
    // ══════════════════════════════════════

    /**
     * 【关键】供弹窗"确定"按钮调用
     * 平台弹窗会调用 组件实例.getSelectedData() 来获取结果
     */
    getSelectedData() {
      return this.selectedUsers
    },

    // ══════════════════════════════════════
    // 头像辅助方法
    // ══════════════════════════════════════

    getInitial(name) {
      if (!name) return '?'
      return name.charAt(name.length - 1)
    },

    getAvatarColor(name) {
      if (!name) return AVATAR_COLORS[0]
      let hash = 0
      for (let i = 0; i < name.length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash)
      }
      return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]
    },
  },
}
</script>

<style lang="scss">
.apaas-custom-avatar-picker {
  height: 100%;
  width: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  overflow: hidden;
  background: #f7f8fa;

  // ── 搜索区 ──
  .search-area {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
    background: #fff;
    padding: 12px 16px;
    border-radius: 8px;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);

    .el-input {
      width: 240px;
    }
    .el-select {
      width: 160px;
    }
  }

  // ── 已选提示条 ──
  .selected-bar {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    flex-shrink: 0;
    padding: 8px 12px;
    background: #e6f7ff;
    border: 1px solid #91d5ff;
    border-radius: 6px;
    font-size: 13px;
    min-height: 40px;
    max-height: 80px;
    overflow-y: auto;

    .selected-bar-title {
      font-weight: 600;
      color: #303133;
      white-space: nowrap;
      flex-shrink: 0;
      line-height: 28px;

      .selected-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 18px;
        height: 18px;
        padding: 0 5px;
        background: #1890ff;
        color: #fff;
        border-radius: 9px;
        font-size: 11px;
        font-weight: 600;
        margin-left: 4px;
        vertical-align: middle;
      }
    }

    .selected-bar-empty {
      color: #c0c4cc;
      font-style: italic;
      line-height: 28px;
    }

    .selected-bar-avatars {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      flex: 1;

      .selected-avatar-item {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        height: 28px;
        padding: 0 6px 0 2px;
        background: #fff;
        border: 1px solid #91d5ff;
        border-radius: 14px;
        font-size: 12px;
        color: #1890ff;
        cursor: default;

        .mini-avatar {
          width: 22px;
          height: 22px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          overflow: hidden;

          .mini-avatar-img {
            width: 100%;
            height: 100%;
            object-fit: cover;
          }
          .mini-avatar-text {
            color: #fff;
            font-size: 11px;
            font-weight: 600;
          }
        }

        .mini-avatar-name {
          max-width: 60px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .mini-avatar-close {
          cursor: pointer;
          color: #909399;
          font-size: 14px;
          line-height: 1;
          &:hover { color: #f56c6c; }
        }
      }
    }

    .bar-clear {
      margin-left: auto;
      color: #909399;
      cursor: pointer;
      font-size: 12px;
      white-space: nowrap;
      flex-shrink: 0;
      line-height: 28px;
      &:hover { color: #f56c6c; }
    }
  }

  // ── 卡片网格 ──
  .avatar-grid-wrapper {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
    padding: 16px;
    position: relative;
  }

  .loading-overlay {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: #909399;
    font-size: 14px;
    gap: 8px;

    i { font-size: 20px; }
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: #c0c4cc;

    i { font-size: 48px; margin-bottom: 12px; }
    p { font-size: 14px; }
  }

  .avatar-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
  }

  .avatar-card {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 20px 12px 16px;
    background: #fafafa;
    border: 2px solid transparent;
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s ease;

    &:hover {
      background: #f0f7ff;
      border-color: #bae7ff;
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(24, 144, 255, 0.12);
    }

    &.avatar-card-selected {
      background: #e6f7ff;
      border-color: #1890ff;
      box-shadow: 0 2px 8px rgba(24, 144, 255, 0.2);
    }

    .card-check {
      position: absolute;
      top: 6px;
      right: 6px;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: #1890ff;
      display: flex;
      align-items: center;
      justify-content: center;

      i {
        color: #fff;
        font-size: 12px;
        font-weight: bold;
      }
    }

    .avatar-circle {
      width: 64px;
      height: 64px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 10px;
      overflow: hidden;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
      flex-shrink: 0;

      .avatar-img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .avatar-initial {
        color: #fff;
        font-size: 24px;
        font-weight: 600;
        user-select: none;
      }
    }

    .card-info {
      text-align: center;
      width: 100%;

      .card-name {
        font-size: 14px;
        font-weight: 600;
        color: #303133;
        margin-bottom: 4px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .card-meta {
        font-size: 12px;
        color: #909399;
        margin-bottom: 2px;
      }
      .card-dept {
        font-size: 12px;
        color: #1890ff;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .card-position {
        font-size: 11px;
        color: #b0b0b0;
        margin-top: 2px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }
  }

  // ── 分页 ──
  .pagination-area {
    flex-shrink: 0;
    display: flex;
    justify-content: flex-end;
    padding: 8px 0 0;
  }
}

// ── 弹窗适配 ──
.x-lov-modal {
  .apaas-custom-avatar-picker {
    padding: 12px;
    gap: 8px;

    .search-area {
      padding: 8px 12px;

      .el-input { width: 180px; }
      .el-select { width: 130px; }
    }

    .selected-bar {
      max-height: 60px;
    }

    .avatar-grid {
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: 8px;
    }

    .avatar-card {
      padding: 14px 8px 12px;

      .avatar-circle {
        width: 48px;
        height: 48px;
        margin-bottom: 8px;

        .avatar-initial { font-size: 18px; }
      }

      .card-info {
        .card-name { font-size: 13px; }
      }
    }
  }
}
</style>

<template>
  <div class="form-widget form-component-approval-flow-list">
    <!-- 列表态显示：简洁模式显示状态 -->
    <div class="list-status" :class="getStatusClass">
      <i :class="getStatusIcon" class="status-icon" v-if="getStatusIcon"></i>
      <span class="status-text">{{ listDisplayText }}</span>
    </div>
  </div>
</template>

<script>
export default {
  name: 'FormComponentApprovalFlowList',
  props: {
    componentConfig: { type: Object, default() { return {} } },
    formValue: { type: [String, Object, Array], default: '' },
    propKey: { type: String, default: '' }
  },
  computed: {
    // 解析审批数据
    approvalData() {
      if (!this.formValue) return []
      if (typeof this.formValue === 'string') {
        try {
          return JSON.parse(this.formValue)
        } catch (e) {
          return []
        }
      }
      if (Array.isArray(this.formValue)) {
        return this.formValue
      }
      return []
    },

    // 获取最新状态
    latestStatus() {
      const list = this.approvalData
      if (!list || list.length === 0) return null
      // 返回最后一个有状态的节点
      for (let i = list.length - 1; i >= 0; i--) {
        if (list[i].status) return list[i].status
      }
      return null
    },

    // 列表态显示文本
    listDisplayText() {
      const list = this.approvalData
      if (!list || list.length === 0) return '无'

      const statusTextMap = {
        'pending': '审批中',
        'approved': '已通过',
        'rejected': '已拒绝',
        'revoked': '已撤回',
        'returned': '已退回',
        'skip': '已跳过'
      }

      if (this.latestStatus) {
        return statusTextMap[this.latestStatus] || this.latestStatus
      }

      // 统计各状态数量
      const statusCounts = {}
      list.forEach(item => {
        const status = item.status || 'pending'
        statusCounts[status] = (statusCounts[status] || 0) + 1
      })

      if (statusCounts.pending) {
        return `审批中 (${list.length})`
      }
      if (statusCounts.approved && !statusCounts.rejected) {
        return '已通过'
      }
      if (statusCounts.rejected) {
        return '已拒绝'
      }

      return `${list.length} 个节点`
    },

    // 状态样式类
    getStatusClass() {
      const status = this.latestStatus
      return {
        'status-pending': status === 'pending',
        'status-approved': status === 'approved',
        'status-rejected': status === 'rejected',
        'status-revoked': status === 'revoked' || status === 'returned' || status === 'skip',
        'status-default': !status
      }
    },

    // 状态图标
    getStatusIcon() {
      const status = this.latestStatus
      const iconMap = {
        'pending': 'el-icon-time',
        'approved': 'el-icon-check',
        'rejected': 'el-icon-close',
        'revoked': 'el-icon-minus',
        'returned': 'el-icon-back',
        'skip': 'el-icon-right'
      }
      return iconMap[status] || ''
    }
  }
}
</script>

<style lang="scss">
.form-component-approval-flow-list {
  .list-status {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 13px;

    .status-icon {
      margin-right: 4px;
      font-size: 12px;
    }

    &.status-pending {
      background-color: #FDF6EC;
      color: #E6A23C;
    }

    &.status-approved {
      background-color: #F0F9EB;
      color: #67C23A;
    }

    &.status-rejected {
      background-color: #FEF0F0;
      color: #F56C6C;
    }

    &.status-revoked {
      background-color: #F4F4F5;
      color: #909399;
    }

    &.status-default {
      color: #909399;
    }
  }
}
</style>

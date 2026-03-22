<template>
  <div class="form-widget form-component-approval-flow-print">
    <!-- 打印态：表格形式展示审批流程 -->
    <table class="approval-print-table" v-if="approvalList && approvalList.length > 0">
      <thead>
        <tr>
          <th>序号</th>
          <th>节点类型</th>
          <th>审批人</th>
          <th>审批状态</th>
          <th>审批意见</th>
          <th>审批时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(item, index) in approvalList" :key="index">
          <td>{{ index + 1 }}</td>
          <td>{{ getNodeTypeName(item.nodeType) }}</td>
          <td>{{ item.approverName || '-' }}</td>
          <td :class="'status-' + item.status">{{ getStatusText(item.status) }}</td>
          <td>{{ item.comment || '-' }}</td>
          <td>{{ item.handleTime || '-' }}</td>
        </tr>
      </tbody>
    </table>
    <div class="empty-state" v-else>无审批记录</div>
  </div>
</template>

<script>
import PrintWidgetMixin from '@/mixin/print-widget.mixin'

export default {
  name: 'FormComponentApprovalFlowPrint',
  mixins: [PrintWidgetMixin],
  data() {
    return {
      approvalList: []
    }
  },
  computed: {
    // 处理formValue
    approvalData() {
      if (!this.formValue) return []
      if (typeof this.formValue === 'string') {
        try {
          return JSON.parse(this.formValue)
        } catch (e) {
          return []
        }
      }
      return this.formValue
    }
  },
  watch: {
    approvalData: {
      handler(newVal) {
        if (Array.isArray(newVal)) {
          this.approvalList = newVal
        } else {
          this.approvalList = []
        }
      },
      immediate: true,
      deep: true
    }
  },
  methods: {
    getNodeTypeName(nodeType) {
      const typeMap = {
        'start': '发起申请',
        'approval': '审批',
        'cc': '抄送',
        'condition': '条件分支',
        'end': '流程结束'
      }
      return typeMap[nodeType] || nodeType || '审批'
    },

    getStatusText(status) {
      const statusMap = {
        'pending': '待处理',
        'approved': '已通过',
        'rejected': '已拒绝',
        'revoked': '已撤回',
        'returned': '已退回',
        'skip': '已跳过'
      }
      return statusMap[status] || status || ''
    }
  }
}
</script>

<style lang="scss">
.form-component-approval-flow-print {
  .approval-print-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;

    th,
    td {
      border: 1px solid #DCDFE6;
      padding: 8px;
      text-align: left;
    }

    th {
      background-color: #F5F7FA;
      font-weight: 600;
      color: #303133;
    }

    td {
      color: #606266;
    }

    .status-pending {
      color: #E6A23C;
    }

    .status-approved {
      color: #67C23A;
    }

    .status-rejected {
      color: #F56C6C;
    }

    .status-revoked,
    .status-returned,
    .status-skip {
      color: #909399;
    }
  }

  .empty-state {
    padding: 16px;
    text-align: center;
    color: #909399;
    font-size: 13px;
    border: 1px dashed #DCDFE6;
    border-radius: 4px;
  }
}
</style>

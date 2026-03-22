<template>
  <div class="form-widget form-component-approval-flow-edit">
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
      <div class="approval-flow-container">
        <!-- 流程时间线 -->
        <div class="approval-timeline" v-if="approvalList && approvalList.length > 0">
          <div
            v-for="(item, index) in approvalList"
            :key="index"
            class="timeline-item"
            :class="getTimelineItemClass(item)"
          >
            <!-- 节点状态指示器 -->
            <div class="timeline-indicator">
              <div class="indicator-dot" :class="getStatusClass(item.status)">
                <i :class="getStatusIcon(item.status)" v-if="item.status !== 'pending'"></i>
              </div>
              <div class="indicator-line" v-if="index < approvalList.length - 1"></div>
            </div>

            <!-- 节点内容 -->
            <div class="timeline-content">
              <div class="content-header">
                <span class="node-type">{{ getNodeTypeName(item.nodeType) }}</span>
                <span class="node-status" :class="'status-' + item.status">
                  {{ getStatusText(item.status) }}
                </span>
              </div>
              <div class="content-body">
                <div class="approver-info" v-if="item.approverName">
                  <el-avatar
                    :size="24"
                    :src="item.approverAvatar"
                    class="approver-avatar"
                  >
                    {{ getAvatarText(item.approverName) }}
                  </el-avatar>
                  <span class="approver-name">{{ item.approverName }}</span>
                </div>
                <div class="approval-comment" v-if="item.comment">
                  {{ item.comment }}
                </div>
                <div class="approval-time" v-if="item.handleTime">
                  {{ item.handleTime }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div class="empty-state" v-else>
          <i class="el-icon-s-claim empty-icon"></i>
          <span class="empty-text">暂无审批记录</span>
        </div>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentApprovalFlowEdit',
  mixins: [FormWidgetMixin],
  data() {
    return {
      // 审批数据列表
      approvalList: []
    }
  },
  computed: {
    // 表单值 - 支持对象或JSON字符串
    editValue: {
      get() {
        if (!this.formValue) return []
        if (typeof this.formValue === 'string') {
          try {
            return JSON.parse(this.formValue)
          } catch (e) {
            return []
          }
        }
        return this.formValue
      },
      set(val) {
        this.formValue = val
      }
    }
  },
  watch: {
    // 监听formValue变化，更新本地审批列表
    editValue: {
      handler(newVal) {
        if (Array.isArray(newVal)) {
          this.approvalList = newVal
        } else if (newVal) {
          try {
            this.approvalList = JSON.parse(newVal)
          } catch (e) {
            this.approvalList = []
          }
        } else {
          this.approvalList = []
        }
      },
      immediate: true,
      deep: true
    }
  },
  methods: {
    // 获取节点类型名称
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

    // 获取状态文本
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
    },

    // 获取状态图标
    getStatusIcon(status) {
      const iconMap = {
        'approved': 'el-icon-check',
        'rejected': 'el-icon-close',
        'revoked': 'el-icon-minus',
        'returned': 'el-icon-back',
        'skip': 'el-icon-right'
      }
      return iconMap[status] || ''
    },

    // 获取状态样式类
    getStatusClass(status) {
      const classMap = {
        'pending': 'status-pending',
        'approved': 'status-approved',
        'rejected': 'status-rejected',
        'revoked': 'status-revoked',
        'returned': 'status-returned',
        'skip': 'status-skip'
      }
      return classMap[status] || 'status-pending'
    },

    // 获取时间线项样式类
    getTimelineItemClass(item) {
      return {
        'is-approved': item.status === 'approved',
        'is-rejected': item.status === 'rejected',
        'is-pending': item.status === 'pending',
        'is-revoked': item.status === 'revoked' || item.status === 'returned' || item.status === 'skip'
      }
    },

    // 获取头像文本（取名字首字母）
    getAvatarText(name) {
      if (!name) return '?'
      return name.charAt(0).toUpperCase()
    }
  }
}
</script>

<style lang="scss">
.form-component-approval-flow-edit {
  .approval-flow-container {
    padding: 8px 0;
  }

  .approval-timeline {
    .timeline-item {
      display: flex;
      padding-bottom: 16px;
      position: relative;

      &:last-child {
        padding-bottom: 0;
      }

      .timeline-indicator {
        display: flex;
        flex-direction: column;
        align-items: center;
        margin-right: 12px;

        .indicator-dot {
          width: 24px;
          height: 24px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 12px;
          color: #fff;
          flex-shrink: 0;
          border: 2px solid #fff;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);

          &.status-pending {
            background-color: #E6A23C;
          }

          &.status-approved {
            background-color: #67C23A;
          }

          &.status-rejected {
            background-color: #F56C6C;
          }

          &.status-revoked,
          &.status-returned,
          &.status-skip {
            background-color: #909399;
          }
        }

        .indicator-line {
          width: 2px;
          flex: 1;
          min-height: 20px;
          background-color: #DCDFE6;
          margin-top: 4px;

          .is-approved & {
            background-color: #67C23A;
          }

          .is-rejected & {
            background-color: #F56C6C;
          }
        }
      }

      .timeline-content {
        flex: 1;
        padding-bottom: 8px;

        .content-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;

          .node-type {
            font-size: 14px;
            font-weight: 500;
            color: #303133;
          }

          .node-status {
            font-size: 12px;
            padding: 2px 8px;
            border-radius: 4px;

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

            &.status-revoked,
            &.status-returned {
              background-color: #F4F4F5;
              color: #909399;
            }
          }
        }

        .content-body {
          background-color: #F5F7FA;
          border-radius: 4px;
          padding: 12px;

          .approver-info {
            display: flex;
            align-items: center;
            margin-bottom: 8px;

            .approver-avatar {
              margin-right: 8px;
              background-color: #409EFF;
              color: #fff;
              font-size: 12px;
            }

            .approver-name {
              font-size: 14px;
              color: #606266;
            }
          }

          .approval-comment {
            font-size: 13px;
            color: #606266;
            line-height: 1.5;
            margin-bottom: 8px;

            &:empty {
              display: none;
            }
          }

          .approval-time {
            font-size: 12px;
            color: #909399;
          }
        }
      }
    }
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 32px 16px;
    background-color: #F5F7FA;
    border-radius: 4px;
    border: 1px dashed #DCDFE6;

    .empty-icon {
      font-size: 48px;
      color: #C0C4CC;
      margin-bottom: 8px;
    }

    .empty-text {
      font-size: 14px;
      color: #909399;
    }
  }
}
</style>

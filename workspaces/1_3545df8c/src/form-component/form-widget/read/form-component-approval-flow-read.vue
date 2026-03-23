<template>
  <div class="form-widget form-component-approval-flow-read">
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
      <div class="approval-flow-read-container">
        <!-- 流程时间线 - 只读态 -->
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
          <span class="empty-text">暂无审批记录</span>
        </div>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentApprovalFlowRead',
  mixins: [FormWidgetMixin],
  data() {
    return {
      approvalList: [],
      platformWorkflowLoading: false
    }
  },
  computed: {
    // 获取组件配置
    componentConfig() {
      return this.widget.customComponentConfig || {}
    },
    // 数据来源类型
    dataSourceType() {
      return this.componentConfig.dataSourceType || 'formValue'
    },
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
        // 只有当数据来源是 formValue 时，才从表单值同步数据
        if (this.dataSourceType === 'formValue') {
          if (Array.isArray(newVal)) {
            this.approvalList = newVal
          } else {
            this.approvalList = []
          }
        }
      },
      immediate: true,
      deep: true
    }
  },
  created() {
    // 如果数据来源是平台流程，则加载平台数据
    if (this.dataSourceType === 'platformWorkflow') {
      this.loadDataFromPlatformWorkflow()
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
    },

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

    getTimelineItemClass(item) {
      return {
        'is-approved': item.status === 'approved',
        'is-rejected': item.status === 'rejected',
        'is-pending': item.status === 'pending',
        'is-revoked': item.status === 'revoked' || item.status === 'returned' || item.status === 'skip'
      }
    },

    getAvatarText(name) {
      if (!name) return '?'
      return name.charAt(0).toUpperCase()
    },

    // 从平台获取流程审批历史
    async loadDataFromPlatformWorkflow() {
      const apiUrl = this.componentConfig.platformApiUrl || '/wflow/common/getFlowHisByBusinessKey'

      this.platformWorkflowLoading = true

      try {
        // 获取当前表单实例ID
        let businessKey = null

        // 方式1：从 formEngineContext.instance 获取
        if (this.formEngineContext && this.formEngineContext.instance) {
          businessKey = this.formEngineContext.instance.documentId ||
                        this.formEngineContext.instance.id ||
                        this.formEngineContext.instance.businessKey
        }

        // 方式2：从表单数据中获取（如果有配置）
        if (!businessKey && this.componentConfig.businessIdField && this.formData) {
          businessKey = this.formData[this.componentConfig.businessIdField]
        }

        // 方式3：从 URL 参数或全局数据获取
        if (!businessKey && this.globalFormData) {
          businessKey = this.globalFormData.id || this.globalFormData.instanceId
        }

        // 方式4：尝试使用 df.sdk 获取
        if (!businessKey) {
          try {
            const dfVue = window.df && window.df.getVue()
            if (dfVue && dfVue.$route) {
              const params = dfVue.$route.params || dfVue.$route.query || {}
              businessKey = params.id || params.instanceId || params.businessKey
            }
          } catch (e) {
            console.warn('[ApprovalFlow-Read] df.sdk 获取失败:', e)
          }
        }

        // 调用平台流程历史接口
        const res = await this.$request({
          url: apiUrl,
          method: 'GET',
          params: { businessKey: businessKey }
        }).asyncThen()

        // 处理返回数据
        this.approvalList = this.parsePlatformWorkflowData(res)

      } catch (e) {
        console.error('[ApprovalFlow-Read] 加载平台流程审批历史失败:', e)
        this.approvalList = []
      } finally {
        this.platformWorkflowLoading = false
      }
    },

    // 解析平台流程历史数据
    parsePlatformWorkflowData(res) {
      if (!res) return []

      if (Array.isArray(res)) {
        return this.transformWorkflowItem(res)
      }
      if (res.data && Array.isArray(res.data)) {
        return this.transformWorkflowItem(res.data)
      }
      if (res.data && res.data.records && Array.isArray(res.data.records)) {
        return this.transformWorkflowItem(res.data.records)
      }
      if (res.records && Array.isArray(res.records)) {
        return this.transformWorkflowItem(res.records)
      }
      if (res.result && Array.isArray(res.result)) {
        return this.transformWorkflowItem(res.result)
      }
      if (res.workflowHistoryList && Array.isArray(res.workflowHistoryList)) {
        return this.transformWorkflowItem(res.workflowHistoryList)
      }

      return []
    },

    // 转换流程历史数据
    transformWorkflowItem(items) {
      if (!Array.isArray(items)) return []

      return items.map(item => {
        return {
          nodeType: item.nodeType || item.taskType || item.type || 'approval',
          nodeName: item.nodeName || item.taskName || item.activityName || item.nodeType || '',
          approverName: item.approverName || item.assigneeName || item.userName || item.createUserName || item.handleUserName || '',
          approverAvatar: item.approverAvatar || item.avatar || '',
          status: this.normalizeWorkflowStatus(item.status || item.state || item.result),
          comment: item.comment || item.remark || item.opinion || item.message || item.content || '',
          handleTime: this.formatWorkflowTime(item.handleTime || item.finishTime || item.endTime || item.createTime),
          createTime: item.createTime || '',
          taskId: item.taskId || item.id || '',
          businessKey: item.businessKey || '',
          _rawData: item
        }
      })
    },

    // 标准化流程状态
    normalizeWorkflowStatus(status) {
      if (!status) return 'pending'

      const statusStr = String(status).toLowerCase()

      if (['pass', 'agree', 'approved', 'complete', 'completed', 'success'].includes(statusStr)) {
        return 'approved'
      }
      if (['reject', 'disagree', 'rejected', 'refuse', 'refused', 'no'].includes(statusStr)) {
        return 'rejected'
      }
      if (['pending', 'processing', 'running', 'active', 'todo', 'await', 'waiting'].includes(statusStr)) {
        return 'pending'
      }
      if (['revoke', 'revoked', 'withdraw', 'withdrawn', 'cancel', 'cancelled'].includes(statusStr)) {
        return 'revoked'
      }
      if (['return', 'returned', 'back'].includes(statusStr)) {
        return 'returned'
      }
      if (['skip', 'skipped', 'jump', 'jumped'].includes(statusStr)) {
        return 'skip'
      }

      return 'pending'
    },

    // 格式化流程时间
    formatWorkflowTime(time) {
      if (!time) return ''

      if (typeof time === 'string' && /^\d{4}-\d{2}-\d{2}/.test(time)) {
        return time
      }

      try {
        const date = new Date(time)
        if (!isNaN(date.getTime())) {
          return this.$dayjs(date).format('YYYY-MM-DD HH:mm:ss')
        }
      } catch (e) {
        console.warn('[ApprovalFlow-Read] 时间格式化失败:', time)
      }

      return String(time)
    }
  }
}
</script>

<style lang="scss">
.form-component-approval-flow-read {
  .approval-flow-read-container {
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
    align-items: center;
    justify-content: center;
    padding: 24px 16px;
    background-color: #F5F7FA;
    border-radius: 4px;

    .empty-text {
      font-size: 14px;
      color: #909399;
    }
  }
}
</style>

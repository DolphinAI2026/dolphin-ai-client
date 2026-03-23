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
        <!-- 加载状态 -->
        <div class="loading-state" v-if="loading">
          <i class="el-icon-loading loading-icon"></i>
          <span class="loading-text">加载中...</span>
        </div>

        <!-- 错误状态 -->
        <div class="error-state" v-else-if="error">
          <i class="el-icon-warning-outline error-icon"></i>
          <span class="error-text">{{ error }}</span>
          <el-button type="text" size="small" @click="refreshData" class="retry-btn">
            <i class="el-icon-refresh"></i> 重试
          </el-button>
        </div>

        <!-- 流程时间线 -->
        <div class="approval-timeline" v-else-if="approvalList && approvalList.length > 0">
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
          <span class="empty-text">{{ componentConfig.emptyText || '暂无审批记录' }}</span>
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
      approvalList: [],
      // 加载状态
      loading: false,
      // 错误信息
      error: null
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
    },
    // 获取组件配置
    componentConfig() {
      return this.widget.customComponentConfig || {}
    },
    // 数据来源类型
    dataSourceType() {
      return this.componentConfig.dataSourceType || 'formValue'
    },
    // API配置
    apiConfig() {
      return {
        url: this.componentConfig.apiUrl || '/api/approval/history',
        method: this.componentConfig.requestMethod || 'GET',
        businessIdField: this.componentConfig.businessIdField || ''
      }
    },
    // 平台流程API配置
    platformWorkflowConfig() {
      return {
        apiUrl: this.componentConfig.platformApiUrl || '/wflow/common/getFlowHisByBusinessKey'
      }
    }
  },
  watch: {
    // 监听formValue变化，更新本地审批列表
    editValue: {
      handler(newVal) {
        // 只有当数据来源是 formValue 时，才同步本地数据
        if (this.dataSourceType === 'formValue') {
          this.syncFromFormValue(newVal)
        }
      },
      immediate: false,
      deep: true
    }
  },
  created() {
    this.initData()
  },
  methods: {
    // 初始化数据
    async initData() {
      const dataSourceType = this.dataSourceType

      if (dataSourceType === 'formValue') {
        this.syncFromFormValue(this.editValue)
      } else if (dataSourceType === 'api') {
        await this.loadDataFromApi()
      } else if (dataSourceType === 'static') {
        this.loadStaticData()
      } else if (dataSourceType === 'platformWorkflow') {
        await this.loadDataFromPlatformWorkflow()
      }
    },

    // 从表单值同步数据
    syncFromFormValue(value) {
      if (Array.isArray(value)) {
        this.approvalList = value
      } else if (value) {
        try {
          this.approvalList = JSON.parse(value)
        } catch (e) {
          this.approvalList = []
        }
      } else {
        this.approvalList = []
      }
    },

    // 从API加载数据
    async loadDataFromApi() {
      const { url, method, businessIdField } = this.apiConfig

      if (!url) {
        this.error = '请先配置API地址'
        return
      }

      this.loading = true
      this.error = null

      try {
        let params = {}

        // 如果配置了业务ID字段，从表单数据中获取值
        if (businessIdField && this.formData) {
          params.businessId = this.formData[businessIdField]
        } else if (this.formEngineContext && this.formEngineContext.instance) {
          // 默认使用表单实例ID
          params.businessId = this.formEngineContext.instance.documentId
        }

        let res
        if (method === 'GET') {
          res = await this.$request({
            url: url.replace('{businessId}', params.businessId || ''),
            method: 'GET',
            params: params.businessId ? { businessId: params.businessId } : undefined
          }).asyncThen()
        } else {
          res = await this.$request({
            url: url,
            method: 'POST',
            data: params
          }).asyncThen()
        }

        // 处理返回数据
        if (res && res.data) {
          this.approvalList = Array.isArray(res.data) ? res.data : [res.data]
        } else if (Array.isArray(res)) {
          this.approvalList = res
        } else {
          this.approvalList = []
        }
      } catch (e) {
        console.error('加载审批历史数据失败:', e)
        this.error = '加载数据失败'
        this.approvalList = []
      } finally {
        this.loading = false
      }
    },

    // 加载静态数据
    loadStaticData() {
      const staticData = this.componentConfig.staticData
      if (staticData) {
        try {
          this.approvalList = JSON.parse(staticData)
        } catch (e) {
          console.error('静态数据JSON格式错误:', e)
          this.approvalList = []
        }
      } else {
        this.approvalList = []
      }
    },

    // 手动刷新数据（供外部调用）
    refreshData() {
      return this.initData()
    },

    // 从平台获取流程审批历史
    async loadDataFromPlatformWorkflow() {
      const { apiUrl } = this.platformWorkflowConfig

      this.loading = true
      this.error = null

      try {
        // 获取当前表单实例ID
        let businessKey = null

        // 方式1：从 formEngineContext.instance 获取
        if (this.formEngineContext && this.formEngineContext.instance) {
          // 优先使用 documentId（文档ID）
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

        if (!businessKey) {
          console.warn('[ApprovalFlow] 未找到表单实例ID，尝试使用df.sdk获取')
          // 尝试使用 df.sdk 获取
          try {
            const dfVue = window.df && window.df.getVue()
            if (dfVue && dfVue.$route) {
              const params = dfVue.$route.params || dfVue.$route.query || {}
              businessKey = params.id || params.instanceId || params.businessKey
            }
          } catch (e) {
            console.warn('[ApprovalFlow] df.sdk 获取失败:', e)
          }
        }

        // 调用平台流程历史接口
        const res = await this.$request({
          url: apiUrl,
          method: 'GET',
          params: { businessKey: businessKey }
        }).asyncThen()

        // 处理返回数据 - 支持多种数据格式
        this.approvalList = this.parsePlatformWorkflowData(res)

      } catch (e) {
        console.error('[ApprovalFlow] 加载平台流程审批历史失败:', e)
        this.error = '加载流程审批历史失败'
        this.approvalList = []
      } finally {
        this.loading = false
      }
    },

    // 解析平台流程历史数据 - 支持多种返回格式
    parsePlatformWorkflowData(res) {
      if (!res) return []

      // 情况1：直接返回数组
      if (Array.isArray(res)) {
        return this.transformWorkflowItem(res)
      }

      // 情况2：{ data: [...] } 格式
      if (res.data && Array.isArray(res.data)) {
        return this.transformWorkflowItem(res.data)
      }

      // 情况3：{ data: { records: [...] } } 分页格式
      if (res.data && res.data.records && Array.isArray(res.data.records)) {
        return this.transformWorkflowItem(res.data.records)
      }

      // 情况4：{ records: [...] } 分页格式
      if (res.records && Array.isArray(res.records)) {
        return this.transformWorkflowItem(res.records)
      }

      // 情况5：{ result: [...] } 格式
      if (res.result && Array.isArray(res.result)) {
        return this.transformWorkflowItem(res.result)
      }

      // 情况6：{ workflowHistoryList: [...] } 得帆平台常用格式
      if (res.workflowHistoryList && Array.isArray(res.workflowHistoryList)) {
        return this.transformWorkflowItem(res.workflowHistoryList)
      }

      console.warn('[ApprovalFlow] 未识别的流程历史数据格式:', res)
      return []
    },

    // 转换流程历史数据为组件需要的格式
    transformWorkflowItem(items) {
      if (!Array.isArray(items)) return []

      return items.map(item => {
        // 尝试多种可能的字段名进行兼容
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
          // 保留原始数据，便于高级配置
          _rawData: item
        }
      })
    },

    // 标准化流程状态
    normalizeWorkflowStatus(status) {
      if (!status) return 'pending'

      const statusStr = String(status).toLowerCase()

      // 已通过/同意/完成
      if (['pass', 'agree', 'approved', 'complete', 'completed', 'success', 'agree', 'end'].includes(statusStr)) {
        return 'approved'
      }

      // 已拒绝/不同意
      if (['reject', 'disagree', 'rejected', 'refuse', 'refused', 'no', 'disagree'].includes(statusStr)) {
        return 'rejected'
      }

      // 待处理/审批中
      if (['pending', 'processing', 'running', 'active', 'todo', 'await', 'waiting'].includes(statusStr)) {
        return 'pending'
      }

      // 已撤回
      if (['revoke', 'revoked', 'withdraw', 'withdrawn', 'cancel', 'cancelled'].includes(statusStr)) {
        return 'revoked'
      }

      // 已退回
      if (['return', 'returned', 'back', 'reject'].includes(statusStr)) {
        return 'returned'
      }

      // 已跳过
      if (['skip', 'skipped', 'jump', 'jumped'].includes(statusStr)) {
        return 'skip'
      }

      return 'pending'
    },

    // 格式化流程时间
    formatWorkflowTime(time) {
      if (!time) return ''

      // 如果已经是字符串且格式合适，直接返回
      if (typeof time === 'string') {
        // 已经是标准格式
        if (/^\d{4}-\d{2}-\d{2}/.test(time)) {
          return time
        }
      }

      // 尝试转换时间戳
      try {
        const date = new Date(time)
        if (!isNaN(date.getTime())) {
          return this.$dayjs(date).format('YYYY-MM-DD HH:mm:ss')
        }
      } catch (e) {
        console.warn('[ApprovalFlow] 时间格式化失败:', time)
      }

      return String(time)
    },

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

  .loading-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 32px 16px;
    background-color: #F5F7FA;
    border-radius: 4px;

    .loading-icon {
      font-size: 32px;
      color: #409EFF;
      margin-bottom: 8px;
    }

    .loading-text {
      font-size: 14px;
      color: #909399;
    }
  }

  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 24px 16px;
    background-color: #FEF0F0;
    border-radius: 4px;
    border: 1px solid #FDE2E2;

    .error-icon {
      font-size: 32px;
      color: #F56C6C;
      margin-bottom: 8px;
    }

    .error-text {
      font-size: 14px;
      color: #F56C6C;
      margin-bottom: 8px;
    }

    .retry-btn {
      color: #409EFF;
      font-size: 13px;
    }
  }
}
</style>

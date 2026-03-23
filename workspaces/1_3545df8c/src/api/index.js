/**
 * 审批流程组件 API 接口定义
 */
const Api = {
  /**
   * 获取审批历史记录列表
   * @param {Object} params - 请求参数
   * @param {string} params.businessId - 业务ID
   * @param {string} [params.businessType] - 业务类型
   * @returns {Promise} 返回审批历史记录列表
   */
  getApprovalHistory(params) {
    return this.$request({
      url: '/api/approval/history',
      method: 'POST',
      data: params
    }).asyncThen(res => {
      return res.data || []
    }).asyncErrorCatch()
  },

  /**
   * 根据业务ID获取审批历史记录（GET方式）
   * @param {string} businessId - 业务ID
   * @returns {Promise} 返回审批历史记录列表
   */
  getApprovalHistoryByBusinessId(businessId) {
    return this.$request({
      url: `/api/approval/history/${businessId}`,
      method: 'GET'
    }).asyncThen(res => {
      return res.data || []
    }).asyncErrorCatch()
  },

  /**
   * 获取审批流程节点配置
   * @param {Object} params - 请求参数
   * @param {string} params.processDefinitionId - 流程定义ID
   * @returns {Promise} 返回流程节点配置
   */
  getApprovalProcessNodes(params) {
    return this.$request({
      url: '/api/approval/process/nodes',
      method: 'GET',
      params
    }).asyncThen(res => {
      return res.data || []
    }).asyncErrorCatch()
  },

  /**
   * 获取当前待审批任务
   * @param {Object} params - 请求参数
   * @param {string} params.userId - 用户ID
   * @returns {Promise} 返回待审批任务列表
   */
  getPendingApprovals(params) {
    return this.$request({
      url: '/api/approval/pending',
      method: 'GET',
      params
    }).asyncThen(res => {
      return res.data || []
    }).asyncErrorCatch()
  }
}

export default Api

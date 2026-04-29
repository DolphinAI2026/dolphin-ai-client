/**
 * 供应商网络图 — 数据查询 API
 * 通过平台全局 API 查询表单数据
 */

const getApaasApi = () => {
  return window.ApaasApi || (window.APaaSSDK && window.APaaSSDK.api) || {}
}

/**
 * 查询表单数据列表
 * @param {string} formId - 表单 ID
 * @param {object} params - 查询参数
 * @returns {Promise<{list: Array, total: number}>}
 */
export function queryFormData(formId, params = {}) {
  const api = getApaasApi()
  if (api.queryFormData) {
    return api.queryFormData(formId, {
      pageNum: 1,
      pageSize: 1000,
      ...params
    })
  }
  // 降级：使用 fetch 调用 OpenAPI
  const baseUrl = window.location.origin
  return fetch(`${baseUrl}/api/open/form/${formId}/data`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pageNum: 1, pageSize: 1000, ...params })
  }).then(res => res.json()).then(data => data.data || { list: [], total: 0 })
}

/**
 * 查询供应商数据
 * @param {string} formId - 供应商表单 ID
 */
export function querySuppliers(formId) {
  return queryFormData(formId)
}

/**
 * 查询合同数据
 * @param {string} formId - 合同表单 ID
 */
export function queryContracts(formId) {
  return queryFormData(formId)
}

/**
 * 查询订单数据
 * @param {string} formId - 订单表单 ID
 */
export function queryOrders(formId) {
  return queryFormData(formId)
}

/**
 * 批量查询所有数据源
 * @param {object} config - { supplierFormId, contractFormId, orderFormId }
 * @returns {Promise<{suppliers: Array, contracts: Array, orders: Array}>}
 */
export function queryAllData(config) {
  const { supplierFormId, contractFormId, orderFormId } = config
  const promises = []

  promises.push(
    supplierFormId
      ? querySuppliers(supplierFormId).then(res => res.list || res || [])
      : Promise.resolve([])
  )
  promises.push(
    contractFormId
      ? queryContracts(contractFormId).then(res => res.list || res || [])
      : Promise.resolve([])
  )
  promises.push(
    orderFormId
      ? queryOrders(orderFormId).then(res => res.list || res || [])
      : Promise.resolve([])
  )

  return Promise.all(promises).then(([suppliers, contracts, orders]) => ({
    suppliers,
    contracts,
    orders
  }))
}

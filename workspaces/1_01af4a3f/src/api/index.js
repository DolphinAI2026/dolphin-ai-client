/**
 * 地图派工 API 定义
 * TODO: 替换为实际 API 地址
 */

const Api = {
  // 查询工单列表
  QUERY_ORDERS: {
    url: '/custom/dispatch/orders',
    method: 'POST',
    disableSuccessMsg: true,
  },

  // 查询人员列表
  QUERY_PERSONS: {
    url: '/custom/dispatch/persons',
    method: 'POST',
    disableSuccessMsg: true,
  },

  // 派工操作
  DISPATCH: {
    url: '/custom/dispatch/assign',
    method: 'POST',
    disableSuccessMsg: true,
  },

  // 获取人员当前位置
  QUERY_PERSON_LOCATIONS: {
    url: '/custom/dispatch/persons/locations',
    method: 'POST',
    disableSuccessMsg: true,
  },
}

export default Api

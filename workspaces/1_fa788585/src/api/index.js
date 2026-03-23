// 工单表单配置
export const FORM_IDS = {
  WORK_ORDER: '69c11b7c2dc93e3506e55ece',
};

export const TAB_IDS = {
  WORK_ORDER: '69c11b7c2dc93e3506e55ee0',
};

const Api = {
  // 查询工单列表
  QUERY_LIST: {
    url: '/xdap-app/business/v2/query/listPageBusinessData',
    method: 'POST',
    disableSuccessMsg: true,
  },
  // 更新工单数据（派单）
  UPDATE_WORK_ORDER: {
    url: '/xdap-app/business/v2/saveBusinessData',
    method: 'POST',
    disableSuccessMsg: false,
  },
};

export default Api;

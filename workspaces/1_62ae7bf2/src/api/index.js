/**
 * 物料拍照验收组件 API 接口定义
 * 使用平台标准 API 端点
 */

// ============ 平台标准 API ============

// 获取业务表单列表（用于选择报价单表单）
export const LIST_BUSINESS_OBJECT_API = {
  url: '/xdap-app/business/v2/query/listBusinessObject',
  method: 'POST',
  description: '获取业务表单列表'
}

// 获取业务表单字段
export const GET_BUSINESS_OBJECT_FIELDS_API = {
  url: '/xdap-app/business/v2/query/getBusinessObjectFields',
  method: 'POST',
  description: '获取业务表单字段列表'
}

// 查询业务数据（用于获取报价单物料列表）
export const QUERY_LIST_PAGE_API = {
  url: '/xdap-app/business/v2/query/listPageBusinessData',
  method: 'POST',
  description: '分页查询业务数据'
}

// ============ AI 识别 API ============

// AI图像识别接口 - 识别物料（需要替换为实际的AI服务地址）
export const MATERIAL_RECOGNIZE_API = {
  url: '/custom/ai/material/recognize',
  method: 'POST',
  description: 'AI图像识别物料接口'
}

// ============ 文件上传 API ============

// 文件上传接口（使用平台标准上传接口）
export const FILE_UPLOAD_API = {
  url: '/xdap-app/file/v2/upload',
  method: 'POST',
  description: '上传物料照片'
}

// 临时文件上传接口（返回base64预览）
export const FILE_UPLOAD_TEMP_API = {
  url: '/xdap-app/file/v2/uploadTemp',
  method: 'POST',
  description: '临时上传物料照片（返回base64）'
}

const Api = {
  // 平台标准API
  LIST_BUSINESS_OBJECT_API,
  GET_BUSINESS_OBJECT_FIELDS_API,
  QUERY_LIST_PAGE_API,
  // AI识别
  MATERIAL_RECOGNIZE_API,
  // 文件上传
  FILE_UPLOAD_API,
  FILE_UPLOAD_TEMP_API
}

export default Api

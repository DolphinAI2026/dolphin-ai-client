/**
 * Mock 人员头像数据
 * 模拟平台 $request 的 .asyncThen().asyncErrorCatch() 链式调用
 */

// ── 模拟人员数据 ──
const MOCK_USERS = [
  { id: '001', name: '张三', employeeNo: 'EMP001', department: '研发部', position: '高级工程师', avatar: '' },
  { id: '002', name: '李四', employeeNo: 'EMP002', department: '研发部', position: '前端开发', avatar: '' },
  { id: '003', name: '王五', employeeNo: 'EMP003', department: '产品部', position: '产品经理', avatar: '' },
  { id: '004', name: '赵六', employeeNo: 'EMP004', department: '设计部', position: 'UI设计师', avatar: '' },
  { id: '005', name: '孙七', employeeNo: 'EMP005', department: '研发部', position: '后端开发', avatar: '' },
  { id: '006', name: '周八', employeeNo: 'EMP006', department: '运维部', position: '运维工程师', avatar: '' },
  { id: '007', name: '吴九', employeeNo: 'EMP007', department: '测试部', position: '测试工程师', avatar: '' },
  { id: '008', name: '郑十', employeeNo: 'EMP008', department: '产品部', position: '产品总监', avatar: '' },
  { id: '009', name: '刘梅', employeeNo: 'EMP009', department: '人事部', position: 'HRBP', avatar: '' },
  { id: '010', name: '陈磊', employeeNo: 'EMP010', department: '财务部', position: '财务主管', avatar: '' },
  { id: '011', name: '杨洋', employeeNo: 'EMP011', department: '研发部', position: '架构师', avatar: '' },
  { id: '012', name: '黄丽', employeeNo: 'EMP012', department: '市场部', position: '市场经理', avatar: '' },
  { id: '013', name: '林涛', employeeNo: 'EMP013', department: '研发部', position: '全栈开发', avatar: '' },
  { id: '014', name: '何静', employeeNo: 'EMP014', department: '设计部', position: '交互设计师', avatar: '' },
  { id: '015', name: '马超', employeeNo: 'EMP015', department: '销售部', position: '销售总监', avatar: '' },
  { id: '016', name: '罗兰', employeeNo: 'EMP016', department: '运维部', position: 'DBA', avatar: '' },
  { id: '017', name: '谢峰', employeeNo: 'EMP017', department: '测试部', position: '自动化测试', avatar: '' },
  { id: '018', name: '韩雪', employeeNo: 'EMP018', department: '人事部', position: '招聘专员', avatar: '' },
  { id: '019', name: '唐伟', employeeNo: 'EMP019', department: '研发部', position: '技术经理', avatar: '' },
  { id: '020', name: '曹丹', employeeNo: 'EMP020', department: '产品部', position: '需求分析师', avatar: '' },
]

const ALL_DEPTS = [...new Set(MOCK_USERS.map(u => u.department))]

function createMockResponse(config) {
  const url = config.url || ''
  const params = config.params || {}

  if (url.indexOf('/custom/avatar/users') > -1) {
    let filtered = [...MOCK_USERS]

    // 关键词筛选
    if (params.keyword) {
      const kw = params.keyword.toLowerCase()
      filtered = filtered.filter(u =>
        u.name.toLowerCase().includes(kw) ||
        u.employeeNo.toLowerCase().includes(kw) ||
        u.department.toLowerCase().includes(kw)
      )
    }

    // 部门筛选
    if (params.department) {
      filtered = filtered.filter(u => u.department === params.department)
    }

    // 分页
    const page = params.page || 1
    const pageSize = params.pageSize || 12
    const total = filtered.length
    const start = (page - 1) * pageSize
    const list = filtered.slice(start, start + pageSize)

    return {
      code: 0,
      data: { list, total, departments: ALL_DEPTS },
      msg: 'ok',
    }
  }

  return { code: 0, data: {}, msg: 'ok' }
}

function createChainable(config) {
  const response = createMockResponse(config)

  const chainable = {
    asyncThen(onSuccess, onError) {
      setTimeout(() => {
        try {
          if (response.code === 0) {
            onSuccess && onSuccess(response)
          } else {
            onError && onError(response)
          }
        } catch (e) {
          console.error('[mock-request] asyncThen error:', e)
        }
      }, 300)
      return chainable
    },
    asyncErrorCatch(onError) {
      // mock 环境一般不触发网络错误
      void onError
      return chainable
    },
  }

  return chainable
}

export function installMockRequest(Vue) {
  Vue.prototype.$request = function (config) {
    console.log('[mock-request]', config.method, config.url, config.params)
    return createChainable(config)
  }
}

/**
 * Mock API 处理器
 * 拦截 /custom/* 请求并返回模拟数据
 * 支持 .asyncThen().asyncErrorCatch() 链式调用
 */

const mockDb = {
  orders: [
    {
      id: 'order-001',
      title: '电梯故障维修',
      address: '朝阳区建国路88号',
      position: [116.477428, 39.91923],
      status: 'pending',
      priority: 'high',
      createTime: '2026-03-23 09:30',
      assignedName: null,
      phone: '010-12345601',
      description: '电梯无法正常运行，有人员被困，请紧急处理。',
      reporter: '物业管理员',
    },
    {
      id: 'order-002',
      title: '空调不制冷',
      address: '海淀区中关村大街1号',
      position: [116.317428, 39.98923],
      status: 'pending',
      priority: 'medium',
      createTime: '2026-03-23 10:15',
      assignedName: null,
      phone: '010-12345602',
      description: '3楼办公室空调不制冷。',
      reporter: '行政部',
    },
    {
      id: 'order-003',
      title: '水管漏水',
      address: '东城区王府井大街100号',
      position: [116.407428, 39.92923],
      status: 'dispatched',
      priority: 'high',
      createTime: '2026-03-23 08:45',
      assignedName: '张三',
      phone: '010-12345603',
      description: '卫生间水管漏水严重。',
      reporter: '保洁员',
    },
    {
      id: 'order-004',
      title: '门锁损坏',
      address: '西城区西单北大街120号',
      position: [116.377428, 39.93923],
      status: 'processing',
      priority: 'low',
      createTime: '2026-03-23 07:20',
      assignedName: '李四',
      phone: '010-12345604',
      description: '会议室门锁损坏，无法上锁。',
      reporter: '前台',
    },
    {
      id: 'order-005',
      title: '电路短路',
      address: '朝阳区望京SOHO',
      position: [116.477428, 39.99923],
      status: 'pending',
      priority: 'high',
      createTime: '2026-03-23 11:00',
      assignedName: null,
      phone: '010-12345605',
      description: '办公室电路跳闸，无法送电。',
      reporter: 'IT部门',
    },
    {
      id: 'order-006',
      title: '窗户玻璃破损',
      address: '海淀区清华科技园',
      position: [116.317428, 39.99923],
      status: 'pending',
      priority: 'medium',
      createTime: '2026-03-23 11:30',
      assignedName: null,
      phone: '010-12345606',
      description: '12层窗户玻璃有裂缝，需要更换。',
      reporter: '安全员',
    },
    {
      id: 'order-007',
      title: '照明灯管更换',
      address: '朝阳区三里屯SOHO',
      position: [116.447428, 39.93923],
      status: 'completed',
      priority: 'low',
      createTime: '2026-03-23 08:00',
      assignedName: '王五',
      phone: '010-12345607',
      description: '走廊灯管闪烁需要更换。',
      reporter: '物业',
    },
  ],

  persons: [
    {
      id: 'person-001',
      name: '张三',
      phone: '13800001001',
      position: [116.457428, 39.92923],
      address: '朝阳区CBD附近',
      status: 'idle',
      currentTask: null,
      distance: null,
      eta: null,
      completedToday: 3,
    },
    {
      id: 'person-002',
      name: '李四',
      phone: '13800001002',
      position: [116.387428, 39.94923],
      address: '西城区金融街',
      status: 'working',
      currentTask: '门锁损坏',
      distance: null,
      eta: null,
      completedToday: 5,
    },
    {
      id: 'person-003',
      name: '王五',
      phone: '13800001003',
      position: [116.507428, 39.89923],
      address: '朝阳区四惠附近',
      status: 'idle',
      currentTask: null,
      distance: null,
      eta: null,
      completedToday: 4,
    },
    {
      id: 'person-004',
      name: '赵六',
      phone: '13800001004',
      position: [116.327428, 39.95923],
      address: '海淀区上地',
      status: 'offline',
      currentTask: null,
      distance: null,
      eta: null,
      completedToday: 0,
    },
    {
      id: 'person-005',
      name: '钱七',
      phone: '13800001005',
      position: [116.397428, 39.95923],
      address: '东城区东直门',
      status: 'idle',
      currentTask: null,
      distance: null,
      eta: null,
      completedToday: 2,
    },
  ],
}

function handleMockRequest(config) {
  const url = config.url
  const method = (config.method || 'GET').toUpperCase()

  return new Promise((resolve, reject) => {
    setTimeout(() => {
      try {
        let response = { success: true, data: null, total: 0 }

        // 查询工单列表
        if (url.includes('/dispatch/orders')) {
          const params = config.data || {}
          let orders = [...mockDb.orders]
          if (params.status) {
            orders = orders.filter(o => o.status === params.status)
          }
          if (params.keyword) {
            const kw = params.keyword.toLowerCase()
            orders = orders.filter(o =>
              (o.title && o.title.toLowerCase().includes(kw)) ||
              (o.address && o.address.toLowerCase().includes(kw))
            )
          }
          response = {
            success: true,
            data: orders,
            total: orders.length,
          }
        }
        // 查询人员列表
        else if (url.includes('/dispatch/persons')) {
          const params = config.data || {}
          let persons = [...mockDb.persons]
          if (params.status) {
            persons = persons.filter(p => p.status === params.status)
          }
          response = {
            success: true,
            data: persons,
            total: persons.length,
          }
        }
        // 查询人员位置
        else if (url.includes('/dispatch/persons/locations')) {
          response = {
            success: true,
            data: mockDb.persons.map(p => ({
              id: p.id,
              position: p.position,
              status: p.status,
            })),
            total: mockDb.persons.length,
          }
        }
        // 派工操作
        else if (url.includes('/dispatch/assign') && method === 'POST') {
          const { orderId, personId } = config.data || {}
          const order = mockDb.orders.find(o => o.id === orderId)
          const person = mockDb.persons.find(p => p.id === personId)
          if (order && person) {
            order.status = 'dispatched'
            order.assignedName = person.name
            person.status = 'working'
            person.currentTask = order.title
            response = {
              success: true,
              data: {
                success: true,
                message: '派工成功',
                order,
                person,
              },
            }
          } else {
            response = { success: false, data: null, message: '工单或人员不存在' }
          }
        }
        // 未知接口
        else {
          response = { success: true, data: null, total: 0 }
        }

        resolve(response)
      } catch (err) {
        reject(err)
      }
    }, 200 + Math.random() * 300)
  })
}

export function installMockRequest(Vue) {
  Vue.prototype.$request = function (config) {
    const ctrl = {}

    // 如果不是 custom 前缀，尝试真实请求（预览环境下会失败，忽略即可）
    if (!config.url.startsWith('/custom/')) {
      let promise = null
      try {
        promise = fetch(config.url, {
          method: (config.method || 'GET').toUpperCase(),
          headers: { 'Content-Type': 'application/json' },
          body: config.data != null ? JSON.stringify(config.data) : undefined,
        }).then(res => {
          if (!res.ok) throw new Error('HTTP ' + res.status)
          return res.json()
        })
      } catch (e) {
        promise = Promise.reject(e)
      }

      ctrl.asyncThen = function (onSuccess, onError) {
        promise.then(onSuccess).catch(onError || function () {})
        return ctrl
      }
      ctrl.asyncErrorCatch = function (onError) {
        promise.catch(onError)
        return ctrl
      }
      return ctrl
    }

    // Mock 请求
    const mockPromise = handleMockRequest(config)

    ctrl.asyncThen = function (onSuccess, onError) {
      mockPromise
        .then(onSuccess)
        .catch(onError || function () {})
      return ctrl
    }

    ctrl.asyncErrorCatch = function (onError) {
      mockPromise.catch(onError)
      return ctrl
    }

    return ctrl
  }
}

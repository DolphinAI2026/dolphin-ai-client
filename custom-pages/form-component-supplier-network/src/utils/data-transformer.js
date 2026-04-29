/**
 * 数据转换工具 — 将表单数据转换为图表所需格式
 */

// 颜色池
const COLOR_POOL = [
  '#409EFF', '#67C23A', '#E6A23C', '#F56C6C',
  '#909399', '#00D1B2', '#7B68EE', '#FF6B6B',
  '#36CFC9', '#597EF7', '#9254DE', '#F759AB'
]

/**
 * 根据字符串哈希获取颜色
 */
function getColorByHash(str) {
  let hash = 0
  for (let i = 0; i < (str || '').length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }
  return COLOR_POOL[Math.abs(hash) % COLOR_POOL.length]
}

/**
 * 安全取值：从表单数据记录中获取字段值
 * 表单数据可能是 { fieldCode: value } 或 { fieldCode: { value: xxx, text: xxx } }
 */
function getFieldValue(record, fieldCode) {
  if (!record || !fieldCode) return ''
  const val = record[fieldCode]
  if (val === null || val === undefined) return ''
  if (typeof val === 'object' && val.value !== undefined) return val.value
  if (typeof val === 'object' && val.text !== undefined) return val.text
  if (typeof val === 'object' && val.name !== undefined) return val.name
  return val
}

function getNumericValue(record, fieldCode) {
  const val = getFieldValue(record, fieldCode)
  const num = parseFloat(val)
  return isNaN(num) ? 0 : num
}

/**
 * 将原始数据转换为力导向图所需的 nodes 和 links
 * @param {Array} suppliers - 供应商列表
 * @param {Array} contracts - 合同列表
 * @param {Array} orders - 订单列表
 * @param {object} fieldMapping - 字段映射配置
 * @returns {{ nodes: Array, links: Array, categories: Array }}
 */
export function transformToNetworkData(suppliers, contracts, orders, fieldMapping = {}) {
  const {
    supplierName = 'supplier_name',
    supplierCategory = 'category',
    supplierRegion = 'region',
    contractSupplier = 'supplier',
    contractAmount = 'amount',
    contractStatus = 'status',
    orderSupplier = 'supplier',
    orderAmount = 'amount'
  } = fieldMapping

  // 收集所有类别
  const categorySet = new Set()
  suppliers.forEach(s => {
    const cat = getFieldValue(s, supplierCategory)
    if (cat) categorySet.add(cat)
  })
  const categories = Array.from(categorySet).map((name, idx) => ({
    name,
    itemStyle: { color: COLOR_POOL[idx % COLOR_POOL.length] }
  }))
  const categoryMap = {}
  categories.forEach((c, i) => { categoryMap[c.name] = i })

  // 构建供应商节点
  const supplierMap = {}
  const nodes = suppliers.map(s => {
    const name = getFieldValue(s, supplierName) || '未知供应商'
    const cat = getFieldValue(s, supplierCategory) || '其他'
    const region = getFieldValue(s, supplierRegion) || '未知地区'
    const id = s.id || s._id || name

    // 计算该供应商的交易总额
    let totalAmount = 0
    contracts.forEach(c => {
      if (getFieldValue(c, contractSupplier) === name || getFieldValue(c, contractSupplier) === id) {
        totalAmount += getNumericValue(c, contractAmount)
      }
    })
    orders.forEach(o => {
      if (getFieldValue(o, orderSupplier) === name || getFieldValue(o, orderSupplier) === id) {
        totalAmount += getNumericValue(o, orderAmount)
      }
    })

    supplierMap[name] = id
    supplierMap[id] = name

    return {
      id: String(id),
      name,
      category: categoryMap[cat] !== undefined ? categoryMap[cat] : 0,
      symbolSize: Math.max(20, Math.min(80, Math.sqrt(totalAmount / 1000) * 10 + 20)),
      value: totalAmount,
      region,
      label: { show: true, fontSize: 11 },
      itemStyle: { color: getColorByHash(cat) }
    }
  })

  // 构建边（合同关系）
  const links = []
  const linkSet = new Set()

  contracts.forEach(c => {
    const supplier = getFieldValue(c, contractSupplier)
    const amount = getNumericValue(c, contractAmount)
    const status = getFieldValue(c, contractStatus)
    if (!supplier) return

    // 合同连接供应商和"本公司"中心节点
    const sourceId = String(supplierMap[supplier] || supplier)
    const targetId = '__company__'
    const key = `${sourceId}-${targetId}`

    if (!linkSet.has(key)) {
      linkSet.add(key)
      links.push({
        source: sourceId,
        target: targetId,
        value: amount,
        lineStyle: {
          width: Math.max(1, Math.min(8, amount / 100000)),
          color: status === '已签订' ? '#67C23A' : status === '已到期' ? '#F56C6C' : '#E6A23C',
          opacity: 0.6
        },
        label: {
          show: false,
          formatter: `${(amount / 10000).toFixed(1)}万`
        }
      })
    }
  })

  // 添加中心节点"本公司"
  nodes.unshift({
    id: '__company__',
    name: '本公司',
    category: -1,
    symbolSize: 60,
    value: 0,
    fixed: true,
    x: 300,
    y: 300,
    label: { show: true, fontSize: 14, fontWeight: 'bold' },
    itemStyle: {
      color: '#409EFF',
      borderColor: '#337ecc',
      borderWidth: 3,
      shadowBlur: 10,
      shadowColor: 'rgba(64, 158, 255, 0.3)'
    }
  })

  return { nodes, links, categories }
}

/**
 * 将原始数据按维度转换为汇总统计
 * @param {Array} suppliers
 * @param {Array} contracts
 * @param {Array} orders
 * @param {string} dimension - 维度: region, category, amount_range, contract_status
 * @param {object} fieldMapping
 * @returns {{ dimension, chartData: Array, summary: object }}
 */
export function transformToDimensionData(suppliers, contracts, orders, dimension, fieldMapping = {}) {
  const {
    supplierName = 'supplier_name',
    supplierCategory = 'category',
    supplierRegion = 'region',
    contractSupplier = 'supplier',
    contractAmount = 'amount',
    contractStatus = 'status',
    orderSupplier = 'supplier',
    orderAmount = 'amount'
  } = fieldMapping

  // 为每个供应商计算汇总
  const supplierStats = suppliers.map(s => {
    const name = getFieldValue(s, supplierName) || '未知'
    const cat = getFieldValue(s, supplierCategory) || '其他'
    const region = getFieldValue(s, supplierRegion) || '未知地区'
    const id = s.id || s._id || name

    let contractTotal = 0, contractCount = 0
    contracts.forEach(c => {
      if (getFieldValue(c, contractSupplier) === name || getFieldValue(c, contractSupplier) === id) {
        contractTotal += getNumericValue(c, contractAmount)
        contractCount++
      }
    })

    let orderTotal = 0, orderCount = 0
    orders.forEach(o => {
      if (getFieldValue(o, orderSupplier) === name || getFieldValue(o, orderSupplier) === id) {
        orderTotal += getNumericValue(o, orderAmount)
        orderCount++
      }
    })

    return {
      name, category: cat, region,
      contractTotal, contractCount,
      orderTotal, orderCount,
      totalAmount: contractTotal + orderTotal
    }
  })

  // 汇总
  const totalAmount = supplierStats.reduce((sum, s) => sum + s.totalAmount, 0)
  const totalContracts = contracts.length
  const totalOrders = orders.length
  const summary = {
    supplierCount: suppliers.length,
    totalContracts,
    totalOrders,
    totalAmount
  }

  let chartData = []

  switch (dimension) {
    case 'region': {
      const grouped = {}
      supplierStats.forEach(s => {
        if (!grouped[s.region]) grouped[s.region] = { count: 0, amount: 0 }
        grouped[s.region].count++
        grouped[s.region].amount += s.totalAmount
      })
      chartData = Object.entries(grouped).map(([name, data]) => ({
        name, count: data.count, amount: data.amount
      })).sort((a, b) => b.amount - a.amount)
      break
    }

    case 'category': {
      const grouped = {}
      supplierStats.forEach(s => {
        if (!grouped[s.category]) grouped[s.category] = { count: 0, amount: 0 }
        grouped[s.category].count++
        grouped[s.category].amount += s.totalAmount
      })
      chartData = Object.entries(grouped).map(([name, data]) => ({
        name, count: data.count, amount: data.amount
      })).sort((a, b) => b.amount - a.amount)
      break
    }

    case 'amount_range': {
      const ranges = [
        { label: '0-10万', min: 0, max: 100000 },
        { label: '10-50万', min: 100000, max: 500000 },
        { label: '50-100万', min: 500000, max: 1000000 },
        { label: '100-500万', min: 1000000, max: 5000000 },
        { label: '500万以上', min: 5000000, max: Infinity }
      ]
      chartData = ranges.map(r => {
        const matched = supplierStats.filter(s => s.totalAmount >= r.min && s.totalAmount < r.max)
        return {
          name: r.label,
          count: matched.length,
          amount: matched.reduce((sum, s) => sum + s.totalAmount, 0)
        }
      })
      break
    }

    case 'contract_status': {
      const grouped = {}
      contracts.forEach(c => {
        const status = getFieldValue(c, contractStatus) || '未知'
        const amount = getNumericValue(c, contractAmount)
        if (!grouped[status]) grouped[status] = { count: 0, amount: 0 }
        grouped[status].count++
        grouped[status].amount += amount
      })
      chartData = Object.entries(grouped).map(([name, data]) => ({
        name, count: data.count, amount: data.amount
      })).sort((a, b) => b.count - a.count)
      break
    }

    default:
      break
  }

  // Top 10 供应商排行
  const topSuppliers = [...supplierStats]
    .sort((a, b) => b.totalAmount - a.totalAmount)
    .slice(0, 10)
    .map((s, idx) => ({ rank: idx + 1, ...s }))

  return { dimension, chartData, summary, topSuppliers }
}

export { COLOR_POOL, getColorByHash, getFieldValue, getNumericValue }

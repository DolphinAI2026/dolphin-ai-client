/**
 * ECharts 配置工厂 — 生成各类图表的 option
 */

import { COLOR_POOL } from './data-transformer'

/**
 * 生成力导向关系图 option
 */
export function buildNetworkOption(networkData) {
  const { nodes, links, categories } = networkData

  return {
    tooltip: {
      trigger: 'item',
      formatter(params) {
        if (params.dataType === 'node') {
          const d = params.data
          if (d.id === '__company__') return '<b>本公司</b>'
          return `
            <div style="font-weight:bold;margin-bottom:4px">${d.name}</div>
            <div>地区：${d.region || '-'}</div>
            <div>交易总额：<b style="color:#E6A23C">${formatAmount(d.value)}</b></div>
          `
        }
        if (params.dataType === 'edge') {
          return `交易金额：${formatAmount(params.data.value)}`
        }
        return ''
      }
    },
    legend: {
      type: 'scroll',
      orient: 'horizontal',
      bottom: 10,
      data: categories.map(c => c.name),
      textStyle: { fontSize: 12, color: '#606266' }
    },
    animationDuration: 1500,
    animationEasingUpdate: 'quinticInOut',
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      focusNodeAdjacency: true,
      force: {
        repulsion: 300,
        gravity: 0.1,
        edgeLength: [100, 250],
        layoutAnimation: true
      },
      categories,
      data: nodes,
      links,
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 6 }
      },
      lineStyle: {
        curveness: 0.1
      },
      label: {
        show: true,
        position: 'bottom',
        fontSize: 11,
        color: '#303133'
      },
      edgeLabel: {
        show: false,
        fontSize: 10
      }
    }]
  }
}

/**
 * 生成饼图 option（品类/地区占比）
 */
export function buildPieOption(data, title = '') {
  return {
    title: {
      text: title,
      left: 'center',
      top: 0,
      textStyle: { fontSize: 14, fontWeight: 500, color: '#303133' }
    },
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)'
    },
    legend: {
      type: 'scroll',
      orient: 'vertical',
      right: 10,
      top: 30,
      bottom: 10,
      textStyle: { fontSize: 11 }
    },
    color: COLOR_POOL,
    series: [{
      type: 'pie',
      radius: ['35%', '65%'],
      center: ['40%', '55%'],
      avoidLabelOverlap: true,
      itemStyle: {
        borderRadius: 6,
        borderColor: '#fff',
        borderWidth: 2
      },
      label: {
        show: true,
        formatter: '{b}\n{d}%',
        fontSize: 11
      },
      emphasis: {
        label: { show: true, fontSize: 14, fontWeight: 'bold' }
      },
      data: data.map(d => ({
        name: d.name,
        value: d.count || d.amount
      }))
    }]
  }
}

/**
 * 生成柱状图 option（地区/金额分布）
 */
export function buildBarOption(data, title = '', valueField = 'amount') {
  const xData = data.map(d => d.name)
  const yData = data.map(d => valueField === 'amount' ? d.amount : d.count)

  return {
    title: {
      text: title,
      left: 'center',
      top: 0,
      textStyle: { fontSize: 14, fontWeight: 500, color: '#303133' }
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter(params) {
        const p = params[0]
        const item = data[p.dataIndex]
        return `
          <div style="font-weight:bold">${p.name}</div>
          <div>供应商数量：${item.count}</div>
          <div>交易金���：${formatAmount(item.amount)}</div>
        `
      }
    },
    grid: {
      left: 60, right: 20, top: 40, bottom: 40
    },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: {
        fontSize: 11,
        interval: 0,
        rotate: xData.length > 6 ? 30 : 0
      }
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        fontSize: 11,
        formatter(val) {
          if (valueField === 'amount') return formatShortAmount(val)
          return val
        }
      }
    },
    color: ['#409EFF'],
    series: [{
      type: 'bar',
      data: yData,
      barMaxWidth: 40,
      itemStyle: {
        borderRadius: [4, 4, 0, 0],
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: '#409EFF' },
            { offset: 1, color: '#79bbff' }
          ]
        }
      },
      emphasis: {
        itemStyle: { color: '#337ecc' }
      }
    }]
  }
}

/**
 * 生成环形图 option（合同状态）
 */
export function buildDonutOption(data, title = '') {
  const statusColors = {
    '已签订': '#67C23A',
    '执行中': '#409EFF',
    '已到��': '#F56C6C',
    '待审批': '#E6A23C',
    '已终止': '#909399'
  }

  return {
    title: {
      text: title,
      left: 'center',
      top: 0,
      textStyle: { fontSize: 14, fontWeight: 500, color: '#303133' }
    },
    tooltip: {
      trigger: 'item',
      formatter(params) {
        return `${params.name}: ${params.value}份 (${params.percent}%)`
      }
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      textStyle: { fontSize: 11 }
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['40%', '55%'],
      avoidLabelOverlap: true,
      itemStyle: {
        borderRadius: 8,
        borderColor: '#fff',
        borderWidth: 3
      },
      label: { show: false },
      emphasis: {
        label: { show: true, fontSize: 14, fontWeight: 'bold' }
      },
      data: data.map(d => ({
        name: d.name,
        value: d.count,
        itemStyle: { color: statusColors[d.name] || COLOR_POOL[data.indexOf(d) % COLOR_POOL.length] }
      }))
    }]
  }
}

/**
 * 金额格式化
 */
function formatAmount(val) {
  if (!val && val !== 0) return '-'
  if (val >= 100000000) return (val / 100000000).toFixed(2) + '亿'
  if (val >= 10000) return (val / 10000).toFixed(2) + '万'
  return val.toLocaleString() + '元'
}

function formatShortAmount(val) {
  if (val >= 100000000) return (val / 100000000).toFixed(1) + '亿'
  if (val >= 10000) return (val / 10000).toFixed(0) + '万'
  return val
}

export { formatAmount, formatShortAmount }

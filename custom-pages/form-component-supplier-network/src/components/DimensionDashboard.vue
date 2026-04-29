<template>
  <div class="dimension-dashboard">
    <!-- 汇总统计卡片 -->
    <div class="dashboard-summary">
      <div class="summary-card" v-for="card in summaryCards" :key="card.label">
        <div class="summary-card__value" :style="{ color: card.color }">{{ card.value }}</div>
        <div class="summary-card__label">{{ card.label }}</div>
      </div>
    </div>

    <!-- 维度选择 -->
    <div class="dashboard-toolbar">
      <DimensionSelector v-model="currentDimension" @change="handleDimensionChange" />
    </div>

    <!-- 图表区域 -->
    <div class="dashboard-charts">
      <div class="chart-row">
        <!-- 左侧：饼图/环形图 -->
        <div class="chart-col chart-col--left">
          <div ref="pieChartRef" class="chart-container"></div>
        </div>
        <!-- 右侧：柱状图 -->
        <div class="chart-col chart-col--right">
          <div ref="barChartRef" class="chart-container"></div>
        </div>
      </div>

      <!-- 排行榜 -->
      <div class="chart-ranking" v-if="topSuppliers.length > 0">
        <div class="ranking-title">Top 10 供应商��行</div>
        <div class="ranking-list">
          <div
            class="ranking-item"
            v-for="item in topSuppliers"
            :key="item.rank"
          >
            <span class="ranking-item__rank" :class="{ 'is-top3': item.rank <= 3 }">
              {{ item.rank }}
            </span>
            <span class="ranking-item__name">{{ item.name }}</span>
            <span class="ranking-item__bar">
              <span
                class="ranking-item__bar-inner"
                :style="{
                  width: getBarWidth(item.totalAmount) + '%',
                  backgroundColor: getBarColor(item.rank)
                }"
              ></span>
            </span>
            <span class="ranking-item__amount">{{ formatAmount(item.totalAmount) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import * as echarts from 'echarts'
import DimensionSelector from './DimensionSelector.vue'
import { buildPieOption, buildBarOption, buildDonutOption, formatAmount } from '../utils/chart-options'

export default {
  name: 'DimensionDashboard',
  components: { DimensionSelector },
  props: {
    dimensionData: {
      type: Object,
      default: () => ({ dimension: 'region', chartData: [], summary: {}, topSuppliers: [] })
    },
    initialDimension: {
      type: String,
      default: 'region'
    }
  },
  data() {
    return {
      currentDimension: this.initialDimension,
      pieChart: null,
      barChart: null
    }
  },
  computed: {
    summaryCards() {
      const s = this.dimensionData.summary || {}
      return [
        { label: '供应商总数', value: s.supplierCount || 0, color: '#409EFF' },
        { label: '合同总数', value: s.totalContracts || 0, color: '#67C23A' },
        { label: '订单总数', value: s.totalOrders || 0, color: '#E6A23C' },
        { label: '交易总额', value: this.formatAmount(s.totalAmount || 0), color: '#F56C6C' }
      ]
    },
    topSuppliers() {
      return this.dimensionData.topSuppliers || []
    },
    maxAmount() {
      if (!this.topSuppliers.length) return 1
      return this.topSuppliers[0].totalAmount || 1
    }
  },
  watch: {
    dimensionData: {
      handler() {
        this.$nextTick(() => this.renderCharts())
      },
      deep: true
    }
  },
  mounted() {
    this.$nextTick(() => this.renderCharts())
    this._resizeHandler = () => {
      if (this.pieChart) this.pieChart.resize()
      if (this.barChart) this.barChart.resize()
    }
    window.addEventListener('resize', this._resizeHandler)
  },
  beforeDestroy() {
    window.removeEventListener('resize', this._resizeHandler)
    if (this.pieChart) { this.pieChart.dispose(); this.pieChart = null }
    if (this.barChart) { this.barChart.dispose(); this.barChart = null }
  },
  methods: {
    formatAmount,
    handleDimensionChange(dim) {
      this.$emit('dimension-change', dim)
    },
    renderCharts() {
      const data = this.dimensionData.chartData || []
      if (!data.length) return

      // 饼图/环形图
      if (this.$refs.pieChartRef) {
        if (this.pieChart) this.pieChart.dispose()
        this.pieChart = echarts.init(this.$refs.pieChartRef)

        let pieOption
        if (this.currentDimension === 'contract_status') {
          pieOption = buildDonutOption(data, '合同状态分布')
        } else {
          const titleMap = {
            region: '地区分布占比',
            category: '品类分布占比',
            amount_range: '金额区间分布'
          }
          pieOption = buildPieOption(data, titleMap[this.currentDimension] || '分布占��')
        }
        this.pieChart.setOption(pieOption)
      }

      // 柱状图
      if (this.$refs.barChartRef) {
        if (this.barChart) this.barChart.dispose()
        this.barChart = echarts.init(this.$refs.barChartRef)

        const titleMap = {
          region: '各地区交易金额',
          category: '各品类交易金额',
          amount_range: '各金额区间供应商数量',
          contract_status: '各状态合同金额'
        }
        const valueField = this.currentDimension === 'amount_range' ? 'count' : 'amount'
        const barOption = buildBarOption(data, titleMap[this.currentDimension] || '数据分布', valueField)
        this.barChart.setOption(barOption)
      }
    },
    getBarWidth(amount) {
      return Math.max(5, (amount / this.maxAmount) * 100)
    },
    getBarColor(rank) {
      if (rank === 1) return '#F56C6C'
      if (rank === 2) return '#E6A23C'
      if (rank === 3) return '#409EFF'
      return '#C0C4CC'
    }
  }
}
</script>

<style lang="scss" scoped>
.dimension-dashboard {
  width: 100%;
}

.dashboard-summary {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;

  .summary-card {
    flex: 1;
    background: #FAFBFC;
    border: 1px solid #EBEEF5;
    border-radius: 8px;
    padding: 16px;
    text-align: center;
    transition: box-shadow 0.2s;

    &:hover {
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    }

    &__value {
      font-size: 24px;
      font-weight: 600;
      line-height: 1.2;
      margin-bottom: 4px;
    }

    &__label {
      font-size: 12px;
      color: #909399;
    }
  }
}

.dashboard-toolbar {
  margin-bottom: 16px;
}

.dashboard-charts {
  .chart-row {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;
  }

  .chart-col {
    flex: 1;
    background: #FAFBFC;
    border: 1px solid #EBEEF5;
    border-radius: 8px;
    padding: 12px;

    &--left { flex: 4; }
    &--right { flex: 6; }
  }

  .chart-container {
    width: 100%;
    height: 300px;
  }
}

.chart-ranking {
  background: #FAFBFC;
  border: 1px solid #EBEEF5;
  border-radius: 8px;
  padding: 16px;

  .ranking-title {
    font-size: 14px;
    font-weight: 500;
    color: #303133;
    margin-bottom: 12px;
  }

  .ranking-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .ranking-item {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 13px;

    &__rank {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 600;
      color: #909399;
      background: #F2F6FC;
      flex-shrink: 0;

      &.is-top3 {
        color: #fff;
        background: #409EFF;
      }
    }

    &__name {
      width: 120px;
      flex-shrink: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: #303133;
    }

    &__bar {
      flex: 1;
      height: 16px;
      background: #F2F6FC;
      border-radius: 8px;
      overflow: hidden;

      &-inner {
        height: 100%;
        border-radius: 8px;
        transition: width 0.6s ease;
      }
    }

    &__amount {
      width: 90px;
      text-align: right;
      flex-shrink: 0;
      color: #606266;
      font-size: 12px;
    }
  }
}
</style>

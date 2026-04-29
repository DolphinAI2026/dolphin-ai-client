<template>
  <div class="network-graph">
    <div ref="chartRef" class="network-graph__chart" :style="{ height: chartHeight + 'px' }"></div>
    <div v-if="!hasData" class="network-graph__empty">
      <i class="el-icon-connection"></i>
      <p>暂无供应商关系数据</p>
    </div>
  </div>
</template>

<script>
import ChartMixin from '../mixin/chart.mixin'
import { buildNetworkOption } from '../utils/chart-options'

export default {
  name: 'NetworkGraph',
  mixins: [ChartMixin],
  props: {
    networkData: {
      type: Object,
      default: () => ({ nodes: [], links: [], categories: [] })
    },
    chartHeight: {
      type: Number,
      default: 500
    }
  },
  computed: {
    hasData() {
      return this.networkData && this.networkData.nodes && this.networkData.nodes.length > 0
    }
  },
  watch: {
    networkData: {
      handler(val) {
        if (val && val.nodes && val.nodes.length > 0) {
          this.$nextTick(() => this.renderChart())
        }
      },
      deep: true
    },
    chartHeight() {
      this.$nextTick(() => this.resizeChart())
    }
  },
  mounted() {
    if (this.hasData) {
      this.$nextTick(() => this.renderChart())
    }
  },
  methods: {
    renderChart() {
      const option = buildNetworkOption(this.networkData)
      this.initChart(this.$refs.chartRef, option)

      // 点击节点事件
      this.chartInstance.on('click', (params) => {
        if (params.dataType === 'node') {
          this.$emit('node-click', params.data)
        }
      })
    }
  }
}
</script>

<style lang="scss" scoped>
.network-graph {
  position: relative;
  width: 100%;

  &__chart {
    width: 100%;
  }

  &__empty {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    text-align: center;
    color: #C0C4CC;

    i {
      font-size: 48px;
      margin-bottom: 12px;
    }

    p {
      font-size: 14px;
      margin: 0;
    }
  }
}
</style>

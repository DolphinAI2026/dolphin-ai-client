import * as echarts from 'echarts'

const ChartMixin = {
  data() {
    return {
      chartInstance: null
    }
  },
  methods: {
    initChart(el, options) {
      if (this.chartInstance) {
        this.chartInstance.dispose()
      }
      this.chartInstance = echarts.init(el)
      this.chartInstance.setOption(options)
      return this.chartInstance
    },
    updateChart(options) {
      if (this.chartInstance) {
        this.chartInstance.setOption(options, { notMerge: true })
      }
    },
    resizeChart() {
      if (this.chartInstance) {
        this.chartInstance.resize()
      }
    },
    disposeChart() {
      if (this.chartInstance) {
        this.chartInstance.dispose()
        this.chartInstance = null
      }
    }
  },
  mounted() {
    this._resizeHandler = () => this.resizeChart()
    window.addEventListener('resize', this._resizeHandler)
  },
  beforeDestroy() {
    window.removeEventListener('resize', this._resizeHandler)
    this.disposeChart()
  }
}

export default ChartMixin

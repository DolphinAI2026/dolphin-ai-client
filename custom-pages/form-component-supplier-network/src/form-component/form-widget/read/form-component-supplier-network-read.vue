<template>
  <x-proxy-form-item
    :widget="widget"
    :validate-info="validateInfo"
    :validate-key="validateKey"
    :form-data="formData"
    :rules="[]"
    :render-scene="renderScene"
  >
    <div class="supplier-network-read">
      <div class="supplier-network-read__header">
        <span class="supplier-network-read__title">
          <i class="el-icon-share"></i>
          {{ widget.label || '供应商网络图' }}
        </span>
        <div class="supplier-network-read__actions">
          <el-radio-group v-model="activeView" size="mini">
            <el-radio-button label="network">网络图</el-radio-button>
            <el-radio-button label="dashboard">汇总看板</el-radio-button>
            <el-radio-button label="both">双视图</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <div class="supplier-network-read__content" v-loading="loading">
        <div v-if="activeView === 'network' || activeView === 'both'" class="supplier-network-read__section">
          <NetworkGraph
            :network-data="networkData"
            :chart-height="componentConfig.chartHeight || 500"
          />
        </div>

        <div v-if="activeView === 'dashboard' || activeView === 'both'" class="supplier-network-read__section">
          <DimensionDashboard
            :dimension-data="dimensionData"
            :initial-dimension="currentDimension"
            @dimension-change="handleDimensionChange"
          />
        </div>

        <div v-if="!loading && !hasData" class="supplier-network-read__empty">
          <i class="el-icon-warning-outline"></i>
          <p>暂无数据</p>
        </div>
      </div>
    </div>
  </x-proxy-form-item>
</template>

<script>
import FormWidgetMixin from '../../../mixin/form-widget.mixin'
import NetworkGraph from '../../../components/NetworkGraph.vue'
import DimensionDashboard from '../../../components/DimensionDashboard.vue'
import { queryAllData } from '../../../api'
import { transformToNetworkData, transformToDimensionData } from '../../../utils/data-transformer'

export default {
  name: 'FormComponentSupplierNetworkRead',
  mixins: [FormWidgetMixin],
  components: { NetworkGraph, DimensionDashboard },
  data() {
    return {
      activeView: 'both',
      loading: false,
      currentDimension: 'region',
      networkData: { nodes: [], links: [], categories: [] },
      dimensionData: { dimension: 'region', chartData: [], summary: {}, topSuppliers: [] },
      rawData: { suppliers: [], contracts: [], orders: [] }
    }
  },
  computed: {
    componentConfig() {
      return (this.widget && this.widget.customComponentConfig) || {}
    },
    hasData() {
      return this.rawData.suppliers.length > 0
    }
  },
  mounted() {
    if (this.componentConfig.defaultView) {
      this.activeView = this.componentConfig.defaultView
    }
    this.fetchData()
  },
  methods: {
    async fetchData() {
      const config = this.componentConfig
      if (!config.supplierFormId) return

      this.loading = true
      try {
        this.rawData = await queryAllData({
          supplierFormId: config.supplierFormId,
          contractFormId: config.contractFormId,
          orderFormId: config.orderFormId
        })
        const fieldMapping = config.fieldMapping || {}
        this.networkData = transformToNetworkData(this.rawData.suppliers, this.rawData.contracts, this.rawData.orders, fieldMapping)
        this.dimensionData = transformToDimensionData(this.rawData.suppliers, this.rawData.contracts, this.rawData.orders, this.currentDimension, fieldMapping)
      } catch (err) {
        console.error('[SupplierNetwork] 数据加载失败:', err)
      } finally {
        this.loading = false
      }
    },
    handleDimensionChange(dim) {
      this.currentDimension = dim
      const config = this.componentConfig
      const fieldMapping = config.fieldMapping || {}
      this.dimensionData = transformToDimensionData(this.rawData.suppliers, this.rawData.contracts, this.rawData.orders, dim, fieldMapping)
    }
  }
}
</script>

<style lang="scss" scoped>
.supplier-network-read {
  width: 100%;
  border: 1px solid #EBEEF5;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;

  &__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: #FAFBFC;
    border-bottom: 1px solid #EBEEF5;
  }

  &__title {
    font-size: 15px;
    font-weight: 500;
    color: #303133;

    i { margin-right: 6px; color: #409EFF; }
  }

  &__actions { display: flex; align-items: center; gap: 12px; }
  &__content { padding: 16px; min-height: 200px; }
  &__section { margin-bottom: 16px; &:last-child { margin-bottom: 0; } }

  &__empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 60px 20px;
    color: #C0C4CC;
    i { font-size: 48px; margin-bottom: 12px; }
    p { font-size: 14px; }
  }
}
</style>

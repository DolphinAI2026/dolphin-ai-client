<template>
  <x-proxy-form-item
    :widget="widget"
    :validate-info="validateInfo"
    :validate-key="validateKey"
    :form-data="formData"
    :rules="validatorRules"
    :render-scene="renderScene"
  >
    <div class="supplier-network-edit">
      <!-- 顶部工具栏 -->
      <div class="supplier-network-edit__header">
        <span class="supplier-network-edit__title">
          <i class="el-icon-share"></i>
          {{ widget.label || '供应商网络图' }}
        </span>
        <div class="supplier-network-edit__actions">
          <el-radio-group v-model="activeView" size="mini">
            <el-radio-button label="network">
              <i class="el-icon-connection"></i> 网络图
            </el-radio-button>
            <el-radio-button label="dashboard">
              <i class="el-icon-data-analysis"></i> 汇总看板
            </el-radio-button>
            <el-radio-button label="both">
              <i class="el-icon-s-grid"></i> 双视图
            </el-radio-button>
          </el-radio-group>
          <el-button
            type="text"
            icon="el-icon-refresh"
            size="mini"
            :loading="loading"
            @click="fetchData"
          >
            刷新
          </el-button>
        </div>
      </div>

      <!-- 内容区域 -->
      <div class="supplier-network-edit__content" v-loading="loading">
        <!-- 网络图 -->
        <div
          v-if="activeView === 'network' || activeView === 'both'"
          class="supplier-network-edit__section"
        >
          <NetworkGraph
            :network-data="networkData"
            :chart-height="componentConfig.chartHeight || 500"
            @node-click="handleNodeClick"
          />
        </div>

        <!-- 汇总看板 -->
        <div
          v-if="activeView === 'dashboard' || activeView === 'both'"
          class="supplier-network-edit__section"
        >
          <DimensionDashboard
            :dimension-data="dimensionData"
            :initial-dimension="currentDimension"
            @dimension-change="handleDimensionChange"
          />
        </div>

        <!-- 无数据提示 -->
        <div v-if="!loading && !hasData" class="supplier-network-edit__empty">
          <i class="el-icon-warning-outline"></i>
          <p>请先在组件设置中配置数据源表单</p>
          <p class="text-hint" v-if="!componentConfig.supplierFormId">
            需要配置供应商、合同和订单表单的 ID
          </p>
        </div>
      </div>

      <!-- 节点详情弹窗 -->
      <el-dialog
        :visible.sync="detailVisible"
        :title="selectedNode ? selectedNode.name : ''"
        width="500px"
        append-to-body
      >
        <div v-if="selectedNode" class="node-detail">
          <div class="node-detail__item">
            <span class="label">地区：</span>
            <span>{{ selectedNode.region || '-' }}</span>
          </div>
          <div class="node-detail__item">
            <span class="label">交易总额：</span>
            <span class="amount">{{ formatNodeAmount(selectedNode.value) }}</span>
          </div>
        </div>
      </el-dialog>
    </div>
  </x-proxy-form-item>
</template>

<script>
import FormWidgetMixin from '../../../mixin/form-widget.mixin'
import NetworkGraph from '../../../components/NetworkGraph.vue'
import DimensionDashboard from '../../../components/DimensionDashboard.vue'
import { queryAllData } from '../../../api'
import { transformToNetworkData, transformToDimensionData } from '../../../utils/data-transformer'
import { formatAmount } from '../../../utils/chart-options'

export default {
  name: 'FormComponentSupplierNetworkEdit',
  mixins: [FormWidgetMixin],
  components: { NetworkGraph, DimensionDashboard },
  data() {
    return {
      activeView: 'both',
      loading: false,
      currentDimension: 'region',
      networkData: { nodes: [], links: [], categories: [] },
      dimensionData: { dimension: 'region', chartData: [], summary: {}, topSuppliers: [] },
      rawData: { suppliers: [], contracts: [], orders: [] },
      detailVisible: false,
      selectedNode: null
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
  watch: {
    'componentConfig.supplierFormId'() {
      this.fetchData()
    },
    'componentConfig.defaultView'(val) {
      if (val) this.activeView = val
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

        this.networkData = transformToNetworkData(
          this.rawData.suppliers,
          this.rawData.contracts,
          this.rawData.orders,
          fieldMapping
        )

        this.dimensionData = transformToDimensionData(
          this.rawData.suppliers,
          this.rawData.contracts,
          this.rawData.orders,
          this.currentDimension,
          fieldMapping
        )
      } catch (err) {
        console.error('[SupplierNetwork] 数据加载失败:', err)
        this.$message && this.$message.error('数据加载失败，请检查数据源配置')
      } finally {
        this.loading = false
      }
    },
    handleDimensionChange(dim) {
      this.currentDimension = dim
      const config = this.componentConfig
      const fieldMapping = config.fieldMapping || {}

      this.dimensionData = transformToDimensionData(
        this.rawData.suppliers,
        this.rawData.contracts,
        this.rawData.orders,
        dim,
        fieldMapping
      )
    },
    handleNodeClick(node) {
      if (node.id === '__company__') return
      this.selectedNode = node
      this.detailVisible = true
    },
    formatNodeAmount(val) {
      return formatAmount(val)
    }
  }
}
</script>

<style lang="scss" scoped>
.supplier-network-edit {
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

    i {
      margin-right: 6px;
      color: #409EFF;
    }
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  &__content {
    padding: 16px;
    min-height: 200px;
  }

  &__section {
    margin-bottom: 16px;

    &:last-child {
      margin-bottom: 0;
    }
  }

  &__empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 60px 20px;
    color: #C0C4CC;

    i {
      font-size: 48px;
      margin-bottom: 12px;
    }

    p {
      font-size: 14px;
      margin: 4px 0;
    }

    .text-hint {
      font-size: 12px;
      color: #DCDFE6;
    }
  }
}

.node-detail {
  &__item {
    display: flex;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid #F2F6FC;

    .label {
      width: 80px;
      color: #909399;
      flex-shrink: 0;
    }

    .amount {
      color: #E6A23C;
      font-weight: 600;
    }
  }
}
</style>

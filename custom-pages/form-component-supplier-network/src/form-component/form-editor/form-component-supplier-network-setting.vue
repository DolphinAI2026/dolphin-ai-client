<template>
  <div class="supplier-network-setting">
    <div class="setting-group">
      <div class="setting-group__title">数据源配置</div>

      <div class="setting-item">
        <div class="setting-item__label">供应商表单 ID</div>
        <el-input
          v-model="config.supplierFormId"
          placeholder="请输入供应商表单 ID"
          size="small"
          @change="handleConfigChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">合同表单 ID</div>
        <el-input
          v-model="config.contractFormId"
          placeholder="请输入合同表单 ID"
          size="small"
          @change="handleConfigChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">订单表单 ID</div>
        <el-input
          v-model="config.orderFormId"
          placeholder="请输入订单表单 ID"
          size="small"
          @change="handleConfigChange"
        />
      </div>
    </div>

    <div class="setting-group">
      <div class="setting-group__title">字段映射</div>
      <div class="setting-group__desc">
        配置各表单中对应字段的字段编码
      </div>

      <div class="setting-item">
        <div class="setting-item__label">供应商名称字段</div>
        <el-input
          v-model="fieldMapping.supplierName"
          placeholder="supplier_name"
          size="small"
          @change="handleFieldMappingChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">供应商分类字段</div>
        <el-input
          v-model="fieldMapping.supplierCategory"
          placeholder="category"
          size="small"
          @change="handleFieldMappingChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">供应商地区字段</div>
        <el-input
          v-model="fieldMapping.supplierRegion"
          placeholder="region"
          size="small"
          @change="handleFieldMappingChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">合同-供应商字段</div>
        <el-input
          v-model="fieldMapping.contractSupplier"
          placeholder="supplier"
          size="small"
          @change="handleFieldMappingChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">合同金额字段</div>
        <el-input
          v-model="fieldMapping.contractAmount"
          placeholder="amount"
          size="small"
          @change="handleFieldMappingChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">合同状态字段</div>
        <el-input
          v-model="fieldMapping.contractStatus"
          placeholder="status"
          size="small"
          @change="handleFieldMappingChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">订单-供应商字段</div>
        <el-input
          v-model="fieldMapping.orderSupplier"
          placeholder="supplier"
          size="small"
          @change="handleFieldMappingChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">订单金额字段</div>
        <el-input
          v-model="fieldMapping.orderAmount"
          placeholder="amount"
          size="small"
          @change="handleFieldMappingChange"
        />
      </div>
    </div>

    <div class="setting-group">
      <div class="setting-group__title">显示设置</div>

      <div class="setting-item">
        <div class="setting-item__label">图表高度 (px)</div>
        <el-slider
          v-model="config.chartHeight"
          :min="300"
          :max="800"
          :step="50"
          show-input
          size="small"
          @change="handleConfigChange"
        />
      </div>

      <div class="setting-item">
        <div class="setting-item__label">默认视图</div>
        <el-radio-group
          v-model="config.defaultView"
          size="small"
          @change="handleConfigChange"
        >
          <el-radio label="network">网络图</el-radio>
          <el-radio label="dashboard">汇总看板</el-radio>
          <el-radio label="both">双视图</el-radio>
        </el-radio-group>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'FormComponentSupplierNetworkSetting',
  props: {
    widget: { type: Object, required: true }
  },
  data() {
    const existing = this.widget.customComponentConfig || {}
    return {
      config: {
        supplierFormId: existing.supplierFormId || '',
        contractFormId: existing.contractFormId || '',
        orderFormId: existing.orderFormId || '',
        chartHeight: existing.chartHeight || 500,
        defaultView: existing.defaultView || 'both',
        fieldMapping: existing.fieldMapping || {}
      },
      fieldMapping: {
        supplierName: (existing.fieldMapping || {}).supplierName || 'supplier_name',
        supplierCategory: (existing.fieldMapping || {}).supplierCategory || 'category',
        supplierRegion: (existing.fieldMapping || {}).supplierRegion || 'region',
        contractSupplier: (existing.fieldMapping || {}).contractSupplier || 'supplier',
        contractAmount: (existing.fieldMapping || {}).contractAmount || 'amount',
        contractStatus: (existing.fieldMapping || {}).contractStatus || 'status',
        orderSupplier: (existing.fieldMapping || {}).orderSupplier || 'supplier',
        orderAmount: (existing.fieldMapping || {}).orderAmount || 'amount'
      }
    }
  },
  methods: {
    handleConfigChange() {
      this.syncConfig()
    },
    handleFieldMappingChange() {
      this.config.fieldMapping = { ...this.fieldMapping }
      this.syncConfig()
    },
    syncConfig() {
      this.$set(this.widget, 'customComponentConfig', { ...this.config })
    }
  }
}
</script>

<style lang="scss" scoped>
.supplier-network-setting {
  padding: 0 4px;

  .setting-group {
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid #F2F6FC;

    &:last-child {
      border-bottom: none;
    }

    &__title {
      font-size: 13px;
      font-weight: 600;
      color: #303133;
      margin-bottom: 8px;
    }

    &__desc {
      font-size: 12px;
      color: #909399;
      margin-bottom: 8px;
    }
  }

  .setting-item {
    margin-bottom: 10px;

    &__label {
      font-size: 12px;
      color: #606266;
      margin-bottom: 4px;
    }
  }
}
</style>

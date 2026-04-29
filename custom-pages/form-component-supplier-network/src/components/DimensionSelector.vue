<template>
  <div class="dimension-selector">
    <el-radio-group v-model="currentDimension" size="small" @change="handleChange">
      <el-radio-button
        v-for="dim in dimensions"
        :key="dim.value"
        :label="dim.value"
      >
        <i :class="dim.icon"></i>
        {{ dim.label }}
      </el-radio-button>
    </el-radio-group>
  </div>
</template>

<script>
export default {
  name: 'DimensionSelector',
  props: {
    value: {
      type: String,
      default: 'region'
    }
  },
  data() {
    return {
      currentDimension: this.value,
      dimensions: [
        { value: 'region', label: '按地区', icon: 'el-icon-location-outline' },
        { value: 'category', label: '���品类', icon: 'el-icon-menu' },
        { value: 'amount_range', label: '按金额', icon: 'el-icon-money' },
        { value: 'contract_status', label: '按合同状态', icon: 'el-icon-document' }
      ]
    }
  },
  watch: {
    value(val) {
      this.currentDimension = val
    }
  },
  methods: {
    handleChange(val) {
      this.$emit('input', val)
      this.$emit('change', val)
    }
  }
}
</script>

<style lang="scss" scoped>
.dimension-selector {
  .el-radio-group {
    display: flex;
    flex-wrap: wrap;
    gap: 0;
  }

  .el-radio-button {
    i {
      margin-right: 4px;
    }
  }
}
</style>

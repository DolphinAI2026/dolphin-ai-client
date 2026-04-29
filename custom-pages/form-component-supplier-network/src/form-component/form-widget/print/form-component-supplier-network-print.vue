<template>
  <div class="supplier-network-print">
    <span>供应商网络图（打印视图）</span>
  </div>
</template>

<script>
export default {
  name: 'FormComponentSupplierNetworkPrint',
  props: {
    widget: { type: Object, default: () => ({}) },
    formData: { type: Object, default: () => ({}) },
    propKey: { type: String, default: '' }
  }
}
</script>

<style lang="scss" scoped>
.supplier-network-print {
  padding: 8px;
  color: #606266;
  font-size: 13px;
}
</style>

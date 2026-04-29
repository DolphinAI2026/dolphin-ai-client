<template>
  <div class="supplier-network-list">
    <i class="el-icon-share"></i>
    <span>供应商网络图</span>
  </div>
</template>

<script>
export default {
  name: 'FormComponentSupplierNetworkList',
  props: {
    componentConfig: { type: Object, default: () => ({}) },
    formValue: { default: '' },
    propKey: { type: String, default: '' }
  }
}
</script>

<style lang="scss" scoped>
.supplier-network-list {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #409EFF;
  font-size: 13px;

  i { font-size: 14px; }
}
</style>

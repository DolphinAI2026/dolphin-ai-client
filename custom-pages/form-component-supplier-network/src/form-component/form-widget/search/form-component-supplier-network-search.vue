<template>
  <div class="supplier-network-search">
    <span class="placeholder-text">供应商网络图</span>
  </div>
</template>

<script>
export default {
  name: 'FormComponentSupplierNetworkSearch',
  props: {
    widget: { type: Object, default: () => ({}) }
  }
}
</script>

<style lang="scss" scoped>
.supplier-network-search {
  .placeholder-text {
    color: #C0C4CC;
    font-size: 13px;
  }
}
</style>

<template>
  <div class="supplier-network-search-ide">
    <span class="placeholder-text">供应商网络图（搜索设计态）</span>
  </div>
</template>

<script>
export default {
  name: 'FormComponentSupplierNetworkSearchIde',
  props: {
    widget: { type: Object, default: () => ({}) }
  }
}
</script>

<style lang="scss" scoped>
.supplier-network-search-ide {
  .placeholder-text {
    color: #C0C4CC;
    font-size: 13px;
  }
}
</style>

<template>
  <div class="apaas-custom-demo">
    <x-list-view :listEngine="listEngine">
      <template #listTable>
        <x-list-table
          ref="xListTableView"
          :treeViewListEngine="listEngine"
          :treeViewInAssoc="true"
          :pageViewComponents="listEngine.listDataControl.tablePanelComponents"
        ></x-list-table>
      </template>
    </x-list-view>
  </div>
</template>
<script>
export default {
  props: {
    listEngine: {
      type: Object,
    },
  },
  data() {
    return {};
  },
  mounted() {
    this.$refs.xListTableView.handlerRowClick = function () {
      return undefined;
    };
  },
  methods: {},
};
</script>

<style lang="scss">
.apaas-custom-demo {
  height: 100%;
}
</style>

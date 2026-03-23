<template>
  <div class="form-widget form-component-approval-flow-search-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
    >
      <el-select disabled size="mini" placeholder="审批状态筛选（设计态预览）">
        <el-option label="全部" value="" />
        <el-option label="待处理" value="pending" />
        <el-option label="已通过" value="approved" />
        <el-option label="已拒绝" value="rejected" />
      </el-select>
    </x-proxy-form-item>
  </div>
</template>

<script>
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'

export default {
  name: 'FormComponentApprovalFlowSearchIde',
  mixins: [SearchIdeWidgetMixin]
}
</script>

<style lang="scss">
.form-component-approval-flow-search-ide {
  .el-select {
    width: 100%;
  }
}
</style>

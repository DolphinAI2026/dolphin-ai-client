<template>
  <div class="form-widget form-component-approval-flow-search">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
    >
      <el-select
        v-model="searchValue"
        clearable
        size="mini"
        placeholder="请选择审批状态"
        @change="handleChange"
      >
        <el-option label="全部" value="" />
        <el-option label="待处理" value="pending" />
        <el-option label="已通过" value="approved" />
        <el-option label="已拒绝" value="rejected" />
        <el-option label="已撤回" value="revoked" />
        <el-option label="已退回" value="returned" />
      </el-select>
    </x-proxy-form-item>
  </div>
</template>

<script>
import SearchWidgetMixin from '@/mixin/search-widget.mixin'

export default {
  name: 'FormComponentApprovalFlowSearch',
  mixins: [SearchWidgetMixin],
  computed: {
    searchValue: {
      get() {
        return this.formValue
      },
      set(val) {
        this.formValue = val
      }
    }
  },
  methods: {
    handleChange(val) {
      this.$emit('search-change', { propKey: this.propKey, value: val })
    }
  }
}
</script>

<style lang="scss">
.form-component-approval-flow-search {
  .el-select {
    width: 100%;
  }
}
</style>

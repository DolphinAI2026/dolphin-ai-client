<template>
  <div class="form-widget form-component-avatar-picker-search-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
    >
      <el-input
        disabled
        size="mini"
        placeholder="人员姓名搜索（设计态预览）"
      />
    </x-proxy-form-item>
  </div>
</template>

<script>
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'

export default {
  name: 'FormComponentAvatarPickerSearchIde',
  mixins: [SearchIdeWidgetMixin]
}
</script>

<style lang="scss">
.form-component-avatar-picker-search-ide {
}
</style>

<template>
  <div class="form-widget form-component-avatar-upload-search-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
    >
      <el-input disabled size="mini" placeholder="头像URL搜索（设计态）" />
    </x-proxy-form-item>
  </div>
</template>

<script>
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'

export default {
  name: 'FormComponentFileUploadSearchIde',
  mixins: [SearchIdeWidgetMixin]
}
</script>

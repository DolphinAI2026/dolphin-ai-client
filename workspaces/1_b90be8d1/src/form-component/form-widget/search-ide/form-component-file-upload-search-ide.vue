<template>
  <div class="form-widget ai-image-recognition-search-ide">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <el-input disabled size="mini" placeholder="AI图片识别（搜索）">
        <i slot="prefix" class="el-icon-picture-outline"></i>
      </el-input>
    </x-proxy-form-item>
  </div>
</template>
<script>
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'
export default { name: 'FormComponentFileUploadSearchIde', mixins: [SearchIdeWidgetMixin] }
</script>

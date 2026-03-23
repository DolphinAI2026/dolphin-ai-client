<template>
  <div class="form-widget form-component-screenshot-search-ide">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <el-input disabled size="mini" placeholder="截图搜索（设计态预览）">
        <template slot="prefix">
          <i class="el-icon-picture-outline-round"></i>
        </template>
      </el-input>
    </x-proxy-form-item>
  </div>
</template>
<script>
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'
export default { name: 'FormComponentAiImageCompareSearchIde', mixins: [SearchIdeWidgetMixin] }
</script>

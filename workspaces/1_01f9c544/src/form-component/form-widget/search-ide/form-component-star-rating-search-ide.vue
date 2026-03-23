<template>
  <div class="form-widget form-component-star-rating-search-ide">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <div class="star-rating-search-ide-wrapper">
        <span class="search-ide-preview">评分搜索（设计态预览）</span>
      </div>
    </x-proxy-form-item>
  </div>
</template>
<script>
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'

export default {
  name: 'FormComponentStarRatingSearchIde',
  mixins: [SearchIdeWidgetMixin]
}
</script>
<style lang="scss">
.star-rating-search-ide-wrapper {
  .search-ide-preview {
    font-size: 12px;
    color: #909399;
    display: inline-block;
    padding: 0 4px;
  }
}
</style>

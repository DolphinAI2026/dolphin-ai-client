<template>
  <div class="form-widget form-component-demo-search-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
    >
      form-component-demo-search-ide
    </x-proxy-form-item>
  </div>
</template>

<script>
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'

export default {
  name: 'FormComponentDemoSearchIde',
  mixins: [SearchIdeWidgetMixin]
}
</script>

<style lang="scss">
.form-component-demo-search-ide {
}
</style>

<template>
  <div class="form-widget form-component-demo-search">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
    >
      form-component-demo-search
    </x-proxy-form-item>
  </div>
</template>

<script>
import SearchWidgetMixin from '@/mixin/search-widget.mixin'

export default {
  name: 'FormComponentDemoSearch',
  mixins: [SearchWidgetMixin]
}
</script>

<style lang="scss">
.form-component-demo-search {
}
</style>

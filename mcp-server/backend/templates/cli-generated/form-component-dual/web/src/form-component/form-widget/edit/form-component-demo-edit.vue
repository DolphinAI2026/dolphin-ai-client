<template>
  <div class="form-widget form-component-demo-edit">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
    >
      form-component-demo-edit
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@shared/mixin/form-widget.mixin'

export default {
  name: 'FormComponentDemoEdit',
  mixins: [FormWidgetMixin]
}
</script>

<style lang="scss">
.form-component-demo-edit {
}
</style>

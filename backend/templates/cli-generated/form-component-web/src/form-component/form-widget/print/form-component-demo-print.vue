<template>
  <div class="form-widget form-component-demo-print">
    form-component-demo-print
  </div>
</template>

<script>
import PrintWidgetMixin from '@/mixin/print-widget.mixin'

export default {
  name: 'FormComponentDemoPrint',
  mixins: [PrintWidgetMixin]
}
</script>

<style lang="scss">
.form-component-demo-print {
}
</style>

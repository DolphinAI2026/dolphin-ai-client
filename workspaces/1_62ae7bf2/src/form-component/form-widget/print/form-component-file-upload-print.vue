<template>
  <div class="form-widget form-component-file-upload-print">
    <span>{{ formValue || '-' }}</span>
  </div>
</template>
<script>
import PrintWidgetMixin from '@/mixin/print-widget.mixin'
export default { name: 'FormComponentFileUploadPrint', mixins: [PrintWidgetMixin] }
</script>

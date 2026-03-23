<template>
  <div class="form-widget form-component-screenshot-print">
    <span v-if="formValue" class="screenshot-print-content">
      <i class="el-icon-picture-outline-round"></i>
      <span>截图</span>
    </span>
    <span v-else>-</span>
  </div>
</template>

<script>
import PrintWidgetMixin from '@/mixin/print-widget.mixin'
export default {
  name: 'FormComponentAiImageComparePrint',
  mixins: [PrintWidgetMixin]
}
</script>

<style lang="scss">
.form-component-screenshot-print {
  .screenshot-print-content {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: #606266;

    i {
      color: #67c23a;
    }
  }
}
</style>

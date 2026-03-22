<template>
  <div class="form-widget form-component-date-picker-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div class="date-picker-ide-preview">
        <i class="el-icon-date date-icon"></i>
        <span class="preview-text">请选择日期范围</span>
      </div>
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {
  name: 'FormComponentDatePickerIde',
  mixins: [FormWidgetMixin]
}
</script>
<style lang="scss">
.form-component-date-picker-ide {
  .date-picker-ide-preview {
    display: flex;
    align-items: center;
    border: 1px dashed #dcdfe6;
    border-radius: 4px;
    padding: 8px 12px;
    background: #fafafa;
    color: #909399;
    font-size: 14px;
    cursor: pointer;

    .date-icon {
      margin-right: 8px;
      font-size: 16px;
    }

    .preview-text {
      color: #c0c4cc;
    }
  }
}
</style>

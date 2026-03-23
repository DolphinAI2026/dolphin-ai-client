<template>
  <div class="form-widget form-component-date-picker-search-ide">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <div class="search-ide-preview">
        <i class="el-icon-date search-icon"></i>
        <span class="preview-text">{{ $t('formWidget.dateRangePicker.selectRange') || '请选择日期范围' }}</span>
      </div>
    </x-proxy-form-item>
  </div>
</template>
<script>
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'
export default {
  name: 'FormComponentDatePickerSearchIde',
  mixins: [SearchIdeWidgetMixin]
}
</script>
<style lang="scss">
.form-component-date-picker-search-ide {
  .search-ide-preview {
    display: flex;
    align-items: center;
    border: 1px dashed #dcdfe6;
    border-radius: 4px;
    padding: 6px 10px;
    background: #fafafa;
    color: #c0c4cc;
    font-size: 12px;
    cursor: pointer;

    .search-icon {
      margin-right: 6px;
      font-size: 14px;
    }

    .preview-text {
      color: #c0c4cc;
    }
  }
}
</style>

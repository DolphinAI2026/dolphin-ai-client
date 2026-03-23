<template>
  <div class="form-widget form-component-date-picker-search">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <el-date-picker
        v-model="searchValue"
        type="daterange"
        format="yyyy-MM-dd"
        value-format="yyyy-MM-dd"
        :placeholder="$t('formWidget.dateRangePicker.selectRange') || '请选择日期范围'"
        :disabled="widget.readOnly"
        :clearable="!widget.readOnly"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        range-separator="~"
        align="left"
        size="mini"
        style="width: 100%;"
        @change="handleChange"
      />
    </x-proxy-form-item>
  </div>
</template>
<script>
import SearchWidgetMixin from '@/mixin/search-widget.mixin'
export default {
  name: 'FormComponentDatePickerSearch',
  mixins: [SearchWidgetMixin],
  computed: {
    searchValue: {
      get() {
        const val = this.value
        if (Array.isArray(val) && val.length === 2) {
          return val
        }
        return null
      },
      set(val) {
        this.$emit('change', val)
      }
    }
  },
  methods: {
    handleChange(val) {
      this.$emit('change', val)
    }
  }
}
</script>
<style lang="scss">
.form-component-date-picker-search {
  .el-date-editor.el-input {
    width: 100%;
  }
}
</style>

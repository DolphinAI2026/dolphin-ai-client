<template>
  <div class="form-widget form-component-date-picker-print">
    <span class="date-range-value">{{ displayValue }}</span>
  </div>
</template>
<script>
import PrintWidgetMixin from '@/mixin/print-widget.mixin'
export default {
  name: 'FormComponentDatePickerPrint',
  mixins: [PrintWidgetMixin],
  computed: {
    displayValue() {
      const val = this.formValue
      if (!val || !Array.isArray(val) || val.length !== 2) {
        return '-'
      }
      const config = this.widget.customComponentConfig || {}
      const format = config.dateFormat || 'yyyy-MM-dd'
      const [startDate, endDate] = val

      // 如果日期已经是格式化字符串，直接使用
      if (typeof startDate === 'string' && typeof endDate === 'string') {
        return `${startDate} ~ ${endDate}`
      }

      // 尝试格式化日期
      try {
        if (this.$dayjs) {
          const start = this.$dayjs(startDate).format(format)
          const end = this.$dayjs(endDate).format(format)
          return `${start} ~ ${end}`
        }
        return `${startDate} ~ ${endDate}`
      } catch (e) {
        return `${startDate} ~ ${endDate}`
      }
    }
  }
}
</script>
<style lang="scss">
.form-component-date-picker-print {
  .date-range-value {
    color: #303133;
    font-size: 14px;
  }
}
</style>

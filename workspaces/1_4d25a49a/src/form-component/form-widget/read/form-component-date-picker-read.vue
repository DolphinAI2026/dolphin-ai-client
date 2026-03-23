<template>
  <div class="form-widget form-component-date-picker-read">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <span class="date-range-value">{{ displayValue }}</span>
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {
  name: 'FormComponentDatePickerRead',
  mixins: [FormWidgetMixin],
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
        const start = this.$dayjs(startDate).format(format)
        const end = this.$dayjs(endDate).format(format)
        return `${start} ~ ${end}`
      } catch (e) {
        return `${startDate} ~ ${endDate}`
      }
    }
  }
}
</script>
<style lang="scss">
.form-component-date-picker-read {
  .date-range-value {
    color: #606266;
    font-size: 14px;
  }
}
</style>

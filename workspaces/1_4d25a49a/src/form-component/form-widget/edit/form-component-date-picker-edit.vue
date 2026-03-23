<template>
  <div class="form-widget form-component-date-picker-edit">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <el-date-picker
        v-model="editValue"
        type="daterange"
        :format="dateFormat"
        :value-format="valueFormat"
        :placeholder="placeholderText"
        :disabled="widget.readOnly"
        :clearable="!widget.readOnly"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        :picker-options="pickerOptions"
        range-separator="~"
        align="left"
        style="width: 100%;"
        @change="handleChange"
      />
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {
  name: 'FormComponentDatePickerEdit',
  mixins: [FormWidgetMixin],
  computed: {
    editValue: {
      get() {
        const val = this.formValue
        if (Array.isArray(val) && val.length === 2) {
          return val
        }
        return null
      },
      set(val) {
        this.formValue = val
      }
    },
    // 日期显示格式
    dateFormat() {
      const config = this.widget.customComponentConfig || {}
      return config.dateFormat || 'yyyy-MM-dd'
    },
    // 值格式
    valueFormat() {
      const config = this.widget.customComponentConfig || {}
      return config.valueFormat || 'yyyy-MM-dd'
    },
    // 占位符文本
    placeholderText() {
      const config = this.widget.customComponentConfig || {}
      return config.placeholder || '请选择日期范围'
    },
    // 快捷选项配置
    pickerOptions() {
      const config = this.widget.customComponentConfig || {}
      const showShortcuts = config.showShortcuts !== false
      const shortcutsConfig = config.shortcutsConfig || {}
      const shortcuts = []

      if (showShortcuts) {
        // 本周
        if (shortcutsConfig.week) {
          shortcuts.push(this.createShortcut('本周', () => {
            const weekStart = this.$dayjs().startOf('week').format('YYYY-MM-DD')
            const weekEnd = this.$dayjs().endOf('week').format('YYYY-MM-DD')
            return [weekStart, weekEnd]
          }))
        }
        // 本月
        if (shortcutsConfig.month) {
          shortcuts.push(this.createShortcut('本月', () => {
            const monthStart = this.$dayjs().startOf('month').format('YYYY-MM-DD')
            const monthEnd = this.$dayjs().endOf('month').format('YYYY-MM-DD')
            return [monthStart, monthEnd]
          }))
        }
        // 本季度
        if (shortcutsConfig.quarter) {
          shortcuts.push(this.createShortcut('本季度', () => {
            const quarterStart = this.$dayjs().startOf('quarter').format('YYYY-MM-DD')
            const quarterEnd = this.$dayjs().endOf('quarter').format('YYYY-MM-DD')
            return [quarterStart, quarterEnd]
          }))
        }
        // 本年
        if (shortcutsConfig.year) {
          shortcuts.push(this.createShortcut('本年', () => {
            const yearStart = this.$dayjs().startOf('year').format('YYYY-MM-DD')
            const yearEnd = this.$dayjs().endOf('year').format('YYYY-MM-DD')
            return [yearStart, yearEnd]
          }))
        }
        // 上周
        if (shortcutsConfig.lastWeek) {
          shortcuts.push(this.createShortcut('上周', () => {
            const lastWeekStart = this.$dayjs().subtract(1, 'week').startOf('week').format('YYYY-MM-DD')
            const lastWeekEnd = this.$dayjs().subtract(1, 'week').endOf('week').format('YYYY-MM-DD')
            return [lastWeekStart, lastWeekEnd]
          }))
        }
        // 上月
        if (shortcutsConfig.lastMonth) {
          shortcuts.push(this.createShortcut('上月', () => {
            const lastMonthStart = this.$dayjs().subtract(1, 'month').startOf('month').format('YYYY-MM-DD')
            const lastMonthEnd = this.$dayjs().subtract(1, 'month').endOf('month').format('YYYY-MM-DD')
            return [lastMonthStart, lastMonthEnd]
          }))
        }
        // 上季度
        if (shortcutsConfig.lastQuarter) {
          shortcuts.push(this.createShortcut('上季度', () => {
            const lastQuarterStart = this.$dayjs().subtract(1, 'quarter').startOf('quarter').format('YYYY-MM-DD')
            const lastQuarterEnd = this.$dayjs().subtract(1, 'quarter').endOf('quarter').format('YYYY-MM-DD')
            return [lastQuarterStart, lastQuarterEnd]
          }))
        }
        // 去年
        if (shortcutsConfig.lastYear) {
          shortcuts.push(this.createShortcut('去年', () => {
            const lastYearStart = this.$dayjs().subtract(1, 'year').startOf('year').format('YYYY-MM-DD')
            const lastYearEnd = this.$dayjs().subtract(1, 'year').endOf('year').format('YYYY-MM-DD')
            return [lastYearStart, lastYearEnd]
          }))
        }
      }

      return { shortcuts }
    }
  },
  methods: {
    handleChange(val) {
      this.$formEventEmit('change', val)
    },
    createShortcut(text, dateRangeFn) {
      return {
        text,
        onClick(picker) {
          picker.$emit('pick', dateRangeFn())
        }
      }
    }
  }
}
</script>
<style lang="scss">
.form-component-date-picker-edit {
  .el-date-editor.el-input {
    width: 100%;
  }
}
</style>

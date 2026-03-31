const PrintWidgetMixin = {
  props: {
    widget: {
      required: true
    },
    componentType: {
      type: String
    },
    formData: {
      required: true
    },
    propKey: {
      type: String,
      default: ''
    },
    inTable: {
      type: Boolean,
      default: false
    },
    formRuleConfig: {
      type: Object,
      default: () => {}
    }
  },
  computed: {
    formValue: {
      get() {
        // 回调函数 当需要读取当前属性值是执行，根据相关数据计算并返回当前属性的值
        return this.propKey ? this.formData[this.propKey] : ''
      },
      set(value) {
        this.formData[this.propKey] = value
        this.$set(this.formData, this.propKey, value)
        // this.$emit('update:formData', { ...this.formData }, this.propKey)
      }
    }
  }
}
export default PrintWidgetMixin

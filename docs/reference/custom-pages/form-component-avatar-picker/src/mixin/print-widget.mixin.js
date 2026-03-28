const PrintWidgetMixin = {
  props: {
    widget: { required: true },
    componentType: { type: String },
    formData: { required: true },
    propKey: { type: String, default: '' },
    inTable: { type: Boolean, default: false },
    formRuleConfig: { type: Object, default: () => {} }
  },
  computed: {
    formValue: {
      get() {
        return this.propKey ? this.formData[this.propKey] : ''
      },
      set(value) {
        this.formData[this.propKey] = value
        this.$set(this.formData, this.propKey, value)
      }
    }
  }
}
export default PrintWidgetMixin

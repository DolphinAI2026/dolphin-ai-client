export default {
  model: { prop: 'value', event: 'change' },
  props: {
    widget: { type: Object, default: () => ({}) },
    compInfo: { type: Object, default: () => ({}) },
    value: { type: Array, default: () => [] },
    placeholder: { type: String },
    searchItemConfig: { type: Object, default: () => ({}) }
  },
  computed: {
    computeValue: {
      get() { return this.value },
      set(value) { this.$emit('change', value) }
    },
    labelStyle() {
      return {
        width: this.searchItemConfig.labelWidth ? this.searchItemConfig.labelWidth / 14 + 'rem' : '',
        textAlign: this.searchItemConfig.labelalign || ''
      }
    }
  }
}

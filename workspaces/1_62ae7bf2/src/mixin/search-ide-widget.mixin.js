export default {
  model: { prop: 'value', event: 'change' },
  props: {
    widget: { type: Object, default: () => ({}) },
    compInfo: { type: Object, default: () => ({}) },
    value: { type: Array, default: () => [] }
  },
  computed: {
    computeValue: {
      get() { return this.value },
      set(value) { this.$emit('change', value) }
    }
  }
}

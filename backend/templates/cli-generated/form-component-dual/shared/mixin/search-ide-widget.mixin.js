export default {
  model: {
    prop: 'value',
    event: 'change'
  },
  props: {
    widget: {
      type: Object,
      default: function() {
        return {}
      }
    },
    compInfo: {
      type: Object,
      default: function() {
        return {}
      }
    },
    value: {
      type: Array,
      default: function() {
        return []
      }
    }
  },
  computed: {
    computeValue: {
      get: function() {
        return this.value
      },
      set: function(value) {
        this.$emit('change', value)
      }
    }
  }
}

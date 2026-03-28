export default {
  model: {
    prop: 'value',
    event: 'change'
  },
  props: {
    widget: {
      type: Object,
      default: function() { return {} }
    },
    compInfo: {
      type: Object,
      default: function() { return {} }
    },
    value: {
      type: Array,
      default: function() { return [] }
    },
    placeholder: {
      type: String
    },
    searchItemConfig: {
      type: Object,
      default: function() { return {} }
    }
  },
  computed: {
    computeValue: {
      get: function() { return this.value },
      set: function(value) { this.$emit('change', value) }
    },
    labelStyle() {
      return {
        width: this.searchItemConfig.labelWidth ? this.searchItemConfig.labelWidth / 14 + 'rem' : '',
        textAlign: this.searchItemConfig.labelalign ? this.searchItemConfig.labelalign : ''
      }
    },
    formItemStyle() {
      return {
        minWidth: this.searchItemConfig.labelWidth && this.searchItemConfig.labelalign === 'right' ? (this.searchItemConfig.labelWidth + 12 + 44) / 14 + 'rem' : ''
      }
    }
  }
}

import WidgetRequiredValidator from '../validator/widget-required-validator'

const EditorFormConfigMixin = {
  props: {
    widgetConfig: {
      required: false,
      default: function() {
        return {}
      }
    },
    componentConfig: {
      required: true
    },
    editConfig: {
      required: true
    },
    configProperty: {},
    formItemList: {},
    formRule: {},
    globalData: {},
    formEngine: {
      type: Object,
      default() {
        return {}
      }
    },
    disabled: {
      type: Boolean,
      default: function() {
        return false
      }
    },
    menuTitle: {
      type: String,
      default: ''
    },
    renderWay: {
      type: String,
      default: () => {
        return 'normal'
      }
    },
    renderDisplayComponentData: {
      type: Array,
      default() {
        return []
      }
    },
    separateConfigFlag: {
      type: Boolean,
      default: false
    }
  },
  inject: ['getPreviewLanguage', 'getI18nShowStatus', 'filterTableFromNodeFields'],
  computed: {
    tenantModule() {
      const sessionStorageTxt = window.sessionStorage && window.sessionStorage.__vuex__session
      return JSON.parse(sessionStorageTxt || '{}').tenantModule || {}
    },
    configValue: {
      get() {
        return this.componentConfig[this.configProperty]
      },
      set(value) {
        this.$set(this.componentConfig, this.configProperty, value)
      }
    },
    typeOptions() {
      return [
        {
          type: 'input',
          label: this.$t('formConfig.selectDataSource.inputValue')
        },
        {
          type: 'rule',
          label: this.$t('formConfig.formulaRule.formulaRule')
        }
      ]
    },
    compDefaultValueType: {
      get() {
        return this.componentConfig.defaultValueType ? this.componentConfig.defaultValueType : 'input'
      },
      set(value) {
        if (value) {
          this.$set(this.componentConfig, 'defaultValueType', value)
        }
      }
    },
    configI18nCode: {
      get() {
        return this.componentConfig[`${this.configProperty}I18nResourceCode`]
      },
      set(value) {
        this.$set(this.componentConfig, `${this.configProperty}I18nResourceCode`, value)
      }
    },
    configI18nAssociated: {
      get() {
        return this.componentConfig[`${this.configProperty}I18nAssociated`]
      },
      set(value) {
        this.$set(this.componentConfig, `${this.configProperty}I18nAssociated`, value)
      }
    },
    configI18nData: {
      get() {
        return this.componentConfig[`${this.configProperty}I18n`]
      },
      set(value) {
        this.$set(this.componentConfig, `${this.configProperty}I18n`, value)
      }
    },
    previewLanguage() {
      return (
        (this.getPreviewLanguage &&
          this.getPreviewLanguage() &&
          this.getPreviewLanguage().replace('-', '')) ||
        (this.$i18n && this.$i18n.locale && this.$i18n.locale.replace('-', ''))
      )
    },
    i18nTextShowStatus() {
      return this.getI18nShowStatus && this.getI18nShowStatus()
    }
  },
  methods: {
    updateConfigByKey(key, value) {
      if (this.editConfig.allowProperties && Array.isArray(this.editConfig.allowProperties)) {
        if (!this.editConfig.allowProperties.includes(key)) {
          throw new Error('无法更新configProperty中未定义的属性配置')
        }
        this.$set(this.componentConfig, key, value)
        this.$forceUpdate()
      }
    },
    getConfigByKey(key) {
      return this.componentConfig[key]
    },
    updateRuleByType(type, value) {
      let currentRules = this.formRule[this.componentConfig.uuid]
      if (!currentRules) {
        currentRules = {
          [type]: []
        }
        currentRules[type].push(value)
      } else {
        if (currentRules[type]) {
          currentRules[type][0] = value
        } else {
          currentRules[type] = [value]
        }
      }
      this.$set(this.formRule, this.componentConfig.uuid, currentRules)
    },
    getRuleByType(type) {
      let currentRules = this.formRule[this.componentConfig.uuid]
      if (!currentRules || !currentRules[type]) {
        return false
      }
      return currentRules[type][0]
    },
    _validate(type, message, trigger = ['blur', 'change'], isI18n = false) {
      const validator = {
        trigger: trigger
      }
      if (typeof type === 'string') {
        validator.type = type
        if (type === 'required') {
          validator.validator = WidgetRequiredValidator(isI18n ? this.$t(message) : message)
        }
        validator.message = isI18n ? this.$t(message) : message
      } else if (typeof type === 'function') {
        validator.validator = type
      }
      return validator
    }
  }
}

export default EditorFormConfigMixin

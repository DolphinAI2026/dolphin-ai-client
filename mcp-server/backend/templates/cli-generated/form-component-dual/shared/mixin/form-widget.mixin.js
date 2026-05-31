import WidgetRequiredValidator from '../validator/widget-required-validator'
import WidgetRegexValidator from '../validator/widget-regex-validator'

const debounce = window._.debounce
const XEventBus = window.APaaSSDK.context.XEventBus
const debounceWaitTime = 150
const AbilityControl = window.Vue.FormEngine.AbilityControl

const isIE = function () {
  const agent = navigator.userAgent.toLowerCase()
  return agent.indexOf('trident') >= 0 || agent.indexOf('msie') >= 0
}

const particularNullCompList = {
  'FORM_WIDGET_AREA': {
    province: {
      code: '',
      name: ''
    },
    city: {
      code: '',
      name: ''
    },
    area: {
      code: '',
      name: ''
    }
  }
} // 字段赋值清空特殊组件空值处理

const FormWidgetMixin = {
  data() {
    return {
      tabindex: '0',
      componentData: null,
      widgetRules: null,
      valueChanged: false,
      bsUnwatch: null,
      bsRefreshDebounce: debounce((newValue, oldValue) => {
        if (newValue !== oldValue) {
          console.log('调用值改变触发业务事件')
          let event
          if (this.widget.isInTable) {
            event = {
              currentRowTableUuid: this.widget.tableUuid,
              currentRowIndex: this.rowIndex,
              vm: this
            }
          }
          if (
            this.formEngine.engineContext.instance.documentId &&
            this.widget.desensitization &&
            this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid] &&
            !this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid].changed
          ) {
            this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid].changed = true
          }

          if (
            this.formEngine.formDataControl.dataFilterComponentList.triggerComponents.includes(
              this.widget.uuid
            )
          ) {
            const dataSelectors = this.formEngine.formDataControl.dataFilterComponentList
              .dataSelectors
            Object.keys(dataSelectors).forEach((key) => {
              if (dataSelectors[key].includes(this.widget.uuid)) {
                XEventBus.emit(`REFRESH_SELECT_BOX`, {
                  uuid: key,
                  currentFormEngineKey: this.formEngine.engineContext.instance.instanceId
                })
              }
            })
          }

          try {
            this.formEngine.bsEventControl.triggerEventValueChange(this.widget, event)
          } catch (error) {
            console.error(error)
          }
        }
      }, 500),
      regexValidatorText: '',
      specialComponents: ['FORM_DATA_STATISTICS', 'FORM_SWITCH_SELECT'],
      debounceFormData: debounce(this.watchFormData, debounceWaitTime),
      debounceFormValue: debounce(this.watchFormValue, debounceWaitTime),
      debounceShowRequired: debounce(this.watchShowRequired, debounceWaitTime)
    }
  },
  props: {
    widget: {
      required: true
    },
    renderScene: {
      type: String,
      required: true,
      validator: function(value) {
        const values = ['ide', 'edit', 'read']
        return values.includes(value)
      }
    },
    propKey: {
      type: String,
      default: ''
    },
    validateKey: {
      type: String,
      default: ''
    },
    validateInfo: {
      type: Object
    },
    formData: {
      type: Object
    },
    globalFormData: {
      type: Object
    },
    globalData: {
      type: Object
    },
    formItemList: {
      type: Array,
      default: function() {
        return []
      }
    },
    valueValidatedStatus: {
      type: Boolean,
      default: true
    },
    rowIndex: {
      type: Number
    },
    tableRowChangeFlag: {
      type: Boolean,
      default: false
    }
  },
  inject: ['renderGlobal', 'themeConfig'],
  computed: {
    isShowButton() {
      return (
        !this.widget.isInTable &&
        this.formValue &&
        this.formEngine.engineContext.instance.documentId &&
        this.widget.showDesensitizationMark &&
        this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid] &&
        !this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid].changed
      )
    },
    formValue: {
      get() {
        this.valueChanged = false
        if (this.valueValidatedStatus) {
          return this.propKey ? this.formData[this.propKey] : undefined
        } else {
          return undefined
        }
      },
      set(value) {
        const { uuid } = this.widget
        if (!value && uuid) {
          const componentConfig = this.formEngine.formDataControl.componentMap.get(uuid)
          componentConfig.showDesensitizationMark = false
        }
        if (this.formData[this.propKey] !== value) {
          this.valueChanged = true
          this.$set(this.formData, this.propKey, value)
          if (!this.specialComponents.includes(this.widget.componentType) && this.formEngine) {
            this.formEngine.formDataControl.ctlFormDataChanged = true
          }
        }
      }
    },
    formEngine() {
      return this.renderGlobal
    },
    formEngineContext() {
      return (this.formEngine && this.formEngine.engineContext) || {}
    },
    validatorRules() {
      let rules = []
      if (this.renderScene === 'edit') {
        if (this.showRequired && !this.widget.hidden) {
          if (this._validate) {
            rules.push(
              this._validate(
                'required',
                `${this.widget.label} ${this.$t('formWidget.common.requiredField')}`
              )
            )
          }
        }
        if (this.widget.validatorStatus) {
          if (this._validate) {
            rules.push(
              this._validate(
                WidgetRegexValidator(
                  `${this.regexValidatorText}`,
                  this.widget.validatorList[0].validatorMessage
                )
              )
            )
          }
        }
        if (this.widgetRules) {
          rules = [...rules, ...this.widgetRules]
        }
      }
      return rules
    },
    showRequired() {
      return this.widget.required && !this.widget.readOnly
    },
    calcUnselectable() {
      if (isIE()) {
        return 'on'
      } else {
        return 'off'
      }
    },
    webFormSettings() {
      return {
        widgetStyle: this.widget.widgetStyle || {},
        border: this.widget.border || {}
      }
    },
    validateMsgPosition() {
      if (this.widget.componentType === 'FORM_WIDGET_SON_TABLE') {
        return 'top'
      }
      return (
        this.themeConfig &&
        this.themeConfig.validateMsgPosition
      ) || 'top'
    },
    ideWidgetPlaceholder() {
      return this.widget.readOnly ? '' : this.widget.defaultValueType === 'rule' ? this.$t('formConfig.formulaRule.formulaRule') : this.widget.placeholder
    },
    tableUuid() {
      const formComponents = this.renderGlobal.formDataControl.allTileFormItemList || []
      return formComponents.filter(comp => comp.componentType === 'FORM_WIDGET_SON_TABLE').map(item => item.uuid)
    },
    formDataWithoutTableData() {
      const formData = { ...this.formData }
      this.tableUuid.forEach(uuid => {
        delete formData[uuid]
      })
      const assoValue = formData
      let jsonObject = ''
      try {
        jsonObject = JSON.stringify(assoValue)
      } catch (error) {
        jsonObject = assoValue
      }
      return jsonObject
    }
  },
  watch: {
    showRequired: {
      handler(newVal, oldValue) {
        this.debounceShowRequired(newVal, oldValue)
      }
    },
    formDataWithoutTableData: {
      handler(newValue, oldValue) {
        if (!this.widget.isInTable && newValue !== oldValue) {
          this.debounceFormData(this.formData)
        }
      },
      deep: true
    }
  },
  created() {
    this.debounceFormData(this.formData)
  },
  mounted() {
    if (this.renderScene === 'edit' || this.renderScene === 'read') {
      const timer = setTimeout(() => {
        clearTimeout(timer)
        this.addBsUnwatch()
      }, 0)
    }
  },
  beforeDestroy() {
    this.debounceShowRequired.cancel()
    this.debounceFormData.cancel()
    this.debounceFormValue.cancel()
  },
  destroyed() {
    if (this.bsUnwatch) {
      this.bsUnwatch()
    }
  },
  methods: {
    watchShowRequired(newVal, oldValue) {
      if (oldValue && !newVal) {
        this.$nextTick(() => {
          this.formEngine.formRef.validateField &&
            this.formEngine.formRef.validateField(this.propKey, () => {
              this.validateInfo.validate = 'validate'
              this.validateInfo.msg = ''
              try {
                this.$el.querySelector('.is-error').classList.remove('is-error')
              } catch (err) {
                console.error(err)
              }
            })
        })
      }
    },
    watchFormValue(newValue, oldValue) {
      if (newValue !== oldValue) {
        this.valueChanged = true
        this.$formEventEmit('change', this.formValue)
      }
    },
    watchFormData(newValue) {
      if (newValue) {
        let titleDescription = ''
        if (
          this.widget.titleDescription &&
          (!this.widget.titleDescriptionOptions || this.widget.titleDescriptionOptions.length === 0)
        ) {
          titleDescription = this.widget.titleDescription
        } else {
          titleDescription = this.titleDesArrToText(newValue, this.widget.titleDescriptionOptions, AbilityControl.TITLE_DESCRIPTION_FORM_FIELD)
        }
        if (
          this.widget.validatorList &&
          this.widget.validatorList[0].validatorConfig.length !== 0
        ) {
          this.regexValidatorText = this.titleDesArrToText(
            newValue,
            this.widget.validatorList[0].validatorConfig,
            AbilityControl.FORM_VALIDATOR_FORM_FIELD,
            true
          )
        }
        const componentConfig = this.renderGlobal.formDataControl.getFormItemByUuid(
          this.widget.uuid
        )
        if (componentConfig) {
          this.$set(componentConfig, 'titleDescription', titleDescription)
        }
      }
    },
    addBsUnwatch() {
      if (this.widget.componentType === 'FORM_WIDGET_SON_TABLE' || this.widget.isInTable) {
        return
      }
      this.bsUnwatch = this.$watch(
        function() {
          let assoValue = this.formValue
          let jsonObject = ''
          if (assoValue === null || typeof assoValue === 'undefined' || (typeof assoValue === 'string' && !assoValue) || (Array.isArray(assoValue) && assoValue.length === 0) || (typeof assoValue === 'object' && JSON.stringify(assoValue) === '{}')) {
            return undefined
          }
          if (typeof assoValue === 'number') {
            assoValue = assoValue.toString()
          }
          try {
            jsonObject = JSON.stringify(assoValue)
          } catch (error) {
            jsonObject = assoValue
          }
          return jsonObject
        },
        (newValue, oldValue) => {
          if (newValue !== oldValue) {
            this.debounceFormValue(newValue, oldValue)
            if (!this.widget.isInTable) {
              this.bsRefreshDebounce(newValue, oldValue)
            }
          }
        }
      )
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
    },
    updatePropValue(key, value) {
      let newValue = value
      if (
        Object.prototype.hasOwnProperty.call(this.formData, key) ||
        (this.formEngine && this.formEngine.formDataControl.ctlComponentMap.has(key))
      ) {
        const widget = this.formEngine.formDataControl.ctlComponentMap.get(key)
        if (Object.keys(particularNullCompList).includes(widget.componentType) && newValue === '') {
          newValue = particularNullCompList[widget.componentType]
        }
        this.$set(this.formData, key, newValue)
        this.formData[key] = newValue
        this.$nextTick(() => {
          this.$emit('formEventEmit', {
            eventName: 'change',
            event: newValue,
            propKey: key,
            widget: widget
          })
        })
      }
    },
    $formEventEmit(eventName, event) {
      this.$emit(eventName, event)
      this.$emit('formEventEmit', {
        eventName: eventName,
        propKey: this.propKey,
        event: event,
        widget: this.widget
      })
    },
    titleDesArrToText(formData, arr, abilityCode, removeNewline = false) {
      let text = ''
      arr &&
        arr.forEach((item) => {
          if (item.type === 'TEXT') {
            text += (removeNewline ? item.value.replace(/\n/g, '') : item.value)
          } else if (item.type === 'COMP') {
            const allComps = this.formEngine.formDataControl.allTileFormItemList
            const compConfig = allComps && allComps.find((_item) => _item.uuid === item.value)
            const textValue = AbilityControl.formatFiledValue({
              fieldType: compConfig && compConfig.componentType,
              value: formData[item.value],
              fieldConfig: compConfig,
              fieldId: item.value,
              abilityCode: abilityCode
            }) || ''
            text += textValue
          }
        })
      text += ''
      return text
    }
  }
}

export default FormWidgetMixin

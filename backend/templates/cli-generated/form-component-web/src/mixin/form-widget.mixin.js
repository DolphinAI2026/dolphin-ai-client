import WidgetRequiredValidator from '@/validator/widget-required-validator'
import WidgetRegexValidator from '@/validator/widget-regex-validator'

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
          // 调用触发业务事件
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
        // 这个值必须匹配下列字符串中的一个
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
        // 回调函数 当需要读取当前属性值是执行，根据相关数据计算并返回当前属性的值
        this.valueChanged = false
        if (this.valueValidatedStatus) {
          return this.propKey ? this.formData[this.propKey] : undefined
        } else {
          return undefined
        }
      },
      set(value) {
        // 值为空 不进行反脱敏操作(新建数据)
        const { uuid } = this.widget
        if (!value && uuid) {
          const componentConfig = this.formEngine.formDataControl.componentMap.get(uuid)
          componentConfig.showDesensitizationMark = false
        }
        if (this.formData[this.propKey] !== value) {
          // 避免tab切换引起的校验
          this.valueChanged = true
          // this.formData[this.propKey] = value
          this.$set(this.formData, this.propKey, value)
          // this.$emit('validate:propKey', this.propKey)
          // this.formEngine.formDataControl.updateFormValue({ ...this.formData })
          // this.$emit('update:formData', { ...this.formData }, this.propKey)
          // this.$formEventEmit('change', value)
          // 数据统计组件、开关组件
          if (!this.specialComponents.includes(this.widget.componentType) && this.formEngine) {
            this.formEngine.formDataControl.ctlFormDataChanged = true
          }
        }
      }
    },
    formEngine() {
      // return this.renderGlobal.formEngine
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
      // return this.widget.required && !this.widget.readOnly && !this.widget.hidden
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
    // 子表组件的uuid数组
    tableUuid() {
      const formComponents = this.renderGlobal.formDataControl.allTileFormItemList || []
      return formComponents.filter(comp => comp.componentType === 'FORM_WIDGET_SON_TABLE').map(item => item.uuid)
    },
    // 非子表数据
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
    // 监听非子表数据变化
    formDataWithoutTableData: {
      handler(newValue, oldValue) {
        // 子表子组件变化移至组件内部执行
        if (!this.widget.isInTable && newValue !== oldValue) {
          this.debounceFormData(this.formData)
        }
      },
      // 注释掉立即执行，移至created生命周期中
      // immediate: true,
      deep: true
    },
    // 注释掉重复的formValue监听，移至到addBsUnwatch中
    // formValue: {
    //   handler(newValue, oldValue) {
    //     this.debounceFormValue(newValue, oldValue)
    //   },
    //   // read表单赋初始值的时候会触发监听，导致重新计算公式规则，故注释掉
    //   // immediate: true,
    //   deep: true
    // }
  },
  created() {
    this.debounceFormData(this.formData)
  },
  mounted() {
    // mixin的beforeCreate > 父beforeCreate > mixin的created > 父created > mixin的beforeMount > 父beforeMount > 子beforeCreate > 子created > 子beforeMount > 子mounted > mixin的mounted >父mounted
    // 刷新表格
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
        // 避免tab切换引起的校验
        this.valueChanged = true
        this.$formEventEmit('change', this.formValue)
      }
    },
    // todo: 组件内部不要监听FormData，后续使用其他方式重构
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
        if (this.widget.componentType === 'FORM_WIDGET_SON_TABLE') {
          if (Array.isArray(this.widget.children) && this.widget.children.length > 0) {
            this.widget.children.forEach((colItem) => {
              let colTitleDescription = ''
              if (
                colItem.titleDescription &&
                (!colItem.titleDescriptionOptions || colItem.titleDescriptionOptions.length === 0)
              ) {
                colTitleDescription = colItem.titleDescription
              } else {
                colTitleDescription = this.titleDesArrToText(
                  newValue,
                  colItem.titleDescriptionOptions,
                  AbilityControl.TITLE_DESCRIPTION_FORM_FIELD
                )
              }
              this.$set(colItem, 'titleDescription', colTitleDescription)
            })
          }
          this.tableValidate && this.tableValidate(newValue)
        }
        const componentConfig = this.renderGlobal.formDataControl.getFormItemByUuid(
          this.widget.uuid
        )
        if (
          this.getDataSelectData &&
          this.renderWay === 'table' &&
          this.widget.dataSelector && this.widget.dataSelector.type === 'SELECT_BOX'
        ) {
          this.getDataSelectData(true)
        }
        if (componentConfig) {
          this.$set(componentConfig, 'titleDescription', titleDescription)
        }
      }
    },
    addBsUnwatch() {
      // 子表和子表子组件对于formValue的监听移至组件内部执行
      if (this.widget.componentType === 'FORM_WIDGET_SON_TABLE' || this.widget.isInTable) {
        return
      }
      this.bsUnwatch = this.$watch(
        function() {
          let assoValue = this.formValue
          let jsonObject = ''
          // 空值之间的变化不触发值改变事件
          if (assoValue === null || typeof assoValue === 'undefined' || (typeof assoValue === 'string' && !assoValue) || (Array.isArray(assoValue) && assoValue.length === 0) || (typeof assoValue === 'object' && JSON.stringify(assoValue) === '{}')) {
            return undefined
          }
          // 如果是数字类型，转为string类型，避免字段类型变化导致数据触发了值改变，例如数字组件原值为0，业务事件字段赋值将其改为string类型"0"，导致触发了值改变
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
      // 生成验证器
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
      // 判断有这个组件时才进行赋值，如果不判断且如果key不存的话则会生成一个不存在的组件值
      let newValue = value
      if (
        Object.prototype.hasOwnProperty.call(this.formData, key) ||
        (this.formEngine && this.formEngine.formDataControl.ctlComponentMap.has(key))
      ) {
        const widget = this.formEngine.formDataControl.ctlComponentMap.get(key)
        // 特殊组件空值处理
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
      // this.formEngine.formDataControl.updateFormValue({ ...this.formData })
      // this.$emit('update:formData', { ...this.formData }, this.key)
    },
    mapAdapter(...args) {
      return this.$formBuildEngine.mapAdapter(args)
    },
    mapEvent(...args) {
      return this.$formBuildEngine.mapEvent(args)
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
    showRealValue() {
      const { documentId, formId } = this.globalData
      const { uuid, isInTable, isDebugModel } = this.widget
      const key = this.widget.modelField.split('.')[1]

      // 如果为业务事件调试模式，则跳过以下逻辑
      if (isDebugModel) return
      this.formEngine.actionControl
        .executeActionWithPromise('GET_FORM_REAL_DATA_ACTION', {
          formId,
          documentId,
          uuid,
          isInTable
        })
        .then((resp) => {
          resp && this.$set(this, 'formValue', resp[key])
          if (!this.widget.isInTable) {
            const componentConfig = this.formEngine.formDataControl.componentMap.get(uuid)
            componentConfig.showDesensitizationMark = false // 清除按钮
          }
          // 子表外组件修改 值的状态(值被修改过)
          // eslint-disable-next-line
          const dataMaskingValue = this.formEngine.formDataControl.dataMaskingValue[
            this.widget.uuid
          ]
          dataMaskingValue.changed = true
          this.$nextTick(() => {
            if (this.widget.renderScene === 'edit') {
              // 仅编辑时执行focus
              this.focus()
            }
          })
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
            // if (
            //   ['FORM_RADIO_INPUT', 'FORM_SELECT_INPUT', 'FORM_CHECKBOX_INPUT', 'FORM_SELECT_INPUT_SINGLE'].includes(
            //     compConfig.componentType
            //   )
            // ) {
            //   let selectData = [...compConfig.chooseOptions].filter((_item) => {
            //     return formData[item.value] && formData[item.value].includes(_item.id)
            //   })
            //   text += getTextFromFormValue(selectData, compConfig)
            // } else {
            //   text += getTextFromFormValue(formData[item.value], compConfig)
            // }
          } else if (item.type === 'RULE') {
            const ruleConfig = JSON.parse(item.detailRuleConfig)
            let rule = {
              ruleId: ruleConfig.advancedRuleId,
              ruleStack: ruleConfig.advancedRuleConfig.advancedRuleList
            }
            let result
            try {
              result = this.formEngine.ruleControl.ruleEngine.executeRule(rule)
            } catch (err) {
              result = ''
            }
            text += result
          } else if (item.type === 'URL') {
            let url = this.titleDesArrToText(formData, JSON.parse(item.urlConfig), abilityCode)
            let hrefUrl = url
            let reg = new RegExp('^(http|https):\\/\\/(?!.*\\s)(?!.*\\.\\.)[^\\s]+$')
            if (!reg.test(url)) {
              hrefUrl = 'about:blank#blocked'
            }
            let urlText = item.hasShowText === 'true' ? item.name : url
            text += urlText ? `<a target="${
              item.newWindowStatus === 'true' ? '_blank' : '_self'
            }" data-target="${
              item.newWindowStatus === 'true' ? '_blank' : '_self'
            }" class="title-description-url" href="${hrefUrl}">${urlText}</a>` : ''
          }
        })
      text += ''
      return text
    }
  }
}

export default FormWidgetMixin

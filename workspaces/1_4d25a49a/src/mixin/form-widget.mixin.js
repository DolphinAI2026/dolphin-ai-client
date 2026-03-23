import WidgetRequiredValidator from '@/validator/widget-required-validator'
import WidgetRegexValidator from '@/validator/widget-regex-validator'

const debounce = window._.debounce
const XEventBus = window.APaaSSDK.context.XEventBus
const debounceWaitTime = 150
const AbilityControl = window.Vue.FormEngine.AbilityControl

const FormWidgetMixin = {
  data() {
    return {
      tabindex: '0', componentData: null, widgetRules: null, valueChanged: false,
      bsUnwatch: null,
      bsRefreshDebounce: debounce((newValue, oldValue) => {
        if (newValue !== oldValue) {
          let event
          if (this.widget.isInTable) {
            event = { currentRowTableUuid: this.widget.tableUuid, currentRowIndex: this.rowIndex, vm: this }
          }
          if (this.formEngine.engineContext.instance.documentId && this.widget.desensitization &&
              this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid] &&
              !this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid].changed) {
            this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid].changed = true
          }
          if (this.formEngine.formDataControl.dataFilterComponentList.triggerComponents.includes(this.widget.uuid)) {
            const dataSelectors = this.formEngine.formDataControl.dataFilterComponentList.dataSelectors
            Object.keys(dataSelectors).forEach((key) => {
              if (dataSelectors[key].includes(this.widget.uuid)) {
                XEventBus.emit('REFRESH_SELECT_BOX', { uuid: key, currentFormEngineKey: this.formEngine.engineContext.instance.instanceId })
              }
            })
          }
          try { this.formEngine.bsEventControl.triggerEventValueChange(this.widget, event) } catch (error) { console.error(error) }
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
    widget: { required: true },
    renderScene: { type: String, required: true, validator: (v) => ['ide', 'edit', 'read'].includes(v) },
    propKey: { type: String, default: '' },
    validateKey: { type: String, default: '' },
    validateInfo: { type: Object },
    formData: { type: Object },
    globalFormData: { type: Object },
    globalData: { type: Object },
    formItemList: { type: Array, default: () => [] },
    valueValidatedStatus: { type: Boolean, default: true },
    rowIndex: { type: Number },
    tableRowChangeFlag: { type: Boolean, default: false }
  },
  inject: ['renderGlobal', 'themeConfig'],
  computed: {
    formValue: {
      get() {
        this.valueChanged = false
        return this.valueValidatedStatus ? (this.propKey ? this.formData[this.propKey] : undefined) : undefined
      },
      set(value) {
        const { uuid } = this.widget
        if (!value && uuid) {
          const cc = this.formEngine.formDataControl.componentMap.get(uuid)
          cc.showDesensitizationMark = false
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
    formEngine() { return this.renderGlobal },
    formEngineContext() { return (this.formEngine && this.formEngine.engineContext) || {} },
    validatorRules() {
      let rules = []
      if (this.renderScene === 'edit') {
        if (this.showRequired && !this.widget.hidden && this._validate) {
          rules.push(this._validate('required', this.widget.label + ' ' + this.$t('formWidget.common.requiredField')))
        }
        if (this.widget.validatorStatus && this.widget.validatorList && this.widget.validatorList[0] && this._validate) {
          rules.push(this._validate(WidgetRegexValidator(this.regexValidatorText, this.widget.validatorList[0].validatorMessage || '')))
        }
        if (this.widgetRules) rules = [...rules, ...this.widgetRules]
      }
      return rules
    },
    showRequired() { return this.widget.required && !this.widget.readOnly },
    webFormSettings() { return { widgetStyle: this.widget.widgetStyle || {}, border: this.widget.border || {} } }
  },
  watch: {
    showRequired: { handler(n, o) { this.debounceShowRequired(n, o) } },
    formDataWithoutTableData: { handler(n, o) { if (!this.widget.isInTable && n !== o) this.debounceFormData(this.formData) }, deep: true }
  },
  created() { this.debounceFormData(this.formData) },
  mounted() {
    if (this.renderScene === 'edit' || this.renderScene === 'read') {
      setTimeout(() => { this.addBsUnwatch() }, 0)
    }
  },
  beforeDestroy() { this.debounceShowRequired.cancel(); this.debounceFormData.cancel(); this.debounceFormValue.cancel() },
  destroyed() { if (this.bsUnwatch) this.bsUnwatch() },
  methods: {
    watchShowRequired() {},
    watchFormValue(n, o) { if (n !== o) { this.valueChanged = true; this.$formEventEmit('change', this.formValue) } },
    watchFormData(newValue) {
      if (newValue) {
        let td = ''
        if (this.widget.titleDescription && (!this.widget.titleDescriptionOptions || !this.widget.titleDescriptionOptions.length)) {
          td = this.widget.titleDescription
        } else {
          td = this.titleDesArrToText(newValue, this.widget.titleDescriptionOptions, AbilityControl.TITLE_DESCRIPTION_FORM_FIELD)
        }
        const cc = this.renderGlobal.formDataControl.getFormItemByUuid(this.widget.uuid)
        if (cc) this.$set(cc, 'titleDescription', td)
      }
    },
    addBsUnwatch() {
      if (this.widget.componentType === 'FORM_WIDGET_SON_TABLE' || this.widget.isInTable) return
      this.bsUnwatch = this.$watch(function() {
        let v = this.formValue
        if (v === null || v === undefined || (typeof v === 'string' && !v) || (Array.isArray(v) && !v.length)) return undefined
        try { return JSON.stringify(v) } catch (e) { return v }
      }, (n, o) => {
        if (n !== o) { this.debounceFormValue(n, o); if (!this.widget.isInTable) this.bsRefreshDebounce(n, o) }
      })
    },
    _validate(type, message, trigger = ['blur', 'change']) {
      const v = { trigger }
      if (typeof type === 'string') { v.type = type; if (type === 'required') v.validator = WidgetRequiredValidator(message); v.message = message }
      else if (typeof type === 'function') v.validator = type
      return v
    },
    updatePropValue(key, value) {
      if (Object.prototype.hasOwnProperty.call(this.formData, key) || (this.formEngine && this.formEngine.formDataControl.ctlComponentMap.has(key))) {
        const w = this.formEngine.formDataControl.ctlComponentMap.get(key)
        this.$set(this.formData, key, value); this.formData[key] = value
        this.$nextTick(() => { this.$emit('formEventEmit', { eventName: 'change', event: value, propKey: key, widget: w }) })
      }
    },
    $formEventEmit(eventName, event) {
      this.$emit(eventName, event)
      this.$emit('formEventEmit', { eventName, propKey: this.propKey, event, widget: this.widget })
    },
    titleDesArrToText(formData, arr, abilityCode) {
      let text = ''
      arr && arr.forEach((item) => {
        if (item.type === 'TEXT') text += item.value
        else if (item.type === 'COMP') {
          const allComps = this.formEngine.formDataControl.allTileFormItemList
          const cc = allComps && allComps.find(i => i.uuid === item.value)
          text += (AbilityControl.formatFiledValue({ fieldType: cc && cc.componentType, value: formData[item.value], fieldConfig: cc, fieldId: item.value, abilityCode }) || '')
        }
      })
      return text
    }
  }
}

export default FormWidgetMixin

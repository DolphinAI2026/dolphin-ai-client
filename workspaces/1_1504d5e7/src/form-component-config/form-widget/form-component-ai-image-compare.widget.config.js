const config = {
  version: 2.0,
  code: 'FORM_CUSTOM_COMPONENT_AI_IMAGE_COMPARE',
  desc: {
    iconType: 'DEFAULT',
    icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#67C23A"><rect x="2" y="3" width="20" height="14" rx="2" stroke="#67C23A" stroke-width="2" fill="none"/><line x1="8" y1="21" x2="16" y2="21" stroke="#67C23A" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="17" x2="12" y2="21" stroke="#67C23A" stroke-width="2" stroke-linecap="round"/></svg>',
    text: '截图工具',
    description: '截图工具'
  },
  instance: { uuid: '$itemUuid', inTable: false },
  component: {
    ide: 'FormComponentAiImageCompareIde',
    edit: 'FormComponentAiImageCompareEdit',
    read: 'FormComponentAiImageCompareRead',
    list: 'FormComponentAiImageCompareList',
    association: 'FormComponentAiImageCompareList',
    lov: 'FormComponentAiImageCompareList',
    print: 'FormComponentAiImageComparePrint',
    search: 'FormComponentAiImageCompareSearch',
    searchIde: 'FormComponentAiImageCompareSearchIde'
  },
  widget: {
    display: {
      label: '截图工具', width: 6, mobileWidth: 12, height: 1,
      hidden: false, readOnly: false, required: false, onlyCreateEdit: false
    },
    allow: { useInTableColumn: true },
    default: { customDefaultKey: 'defaultValue', value: '' },
    validator: { uniqueCheck: false },
    validatorList: [{ validatorConfig: [], validatorMessage: '' }],
    special: { frontBusinessObjectComponentType: 'BOF_TEXT', saveWithHidden: false },
    customComponentConfig: {
      buttonText: '截图',
      maxSize: 10,
      fileTypes: '.jpg,.jpeg,.png',
      showPreview: true
    },
    componentModelField: ['TEXT'],
    editor: {
      config: [
        'INFO', 'LABEL', 'FIELD_CODE', 'TITLE_DESCRIPTION', 'WIDTH',
        'FORM_CUSTOM_COMPONENT_AI_IMAGE_COMPARE_SETTING',
        'FORMULA_RULE', 'HIDDEN', 'READONLY', 'REQUIRED', 'EDITONNEW',
        'UNIQUE', 'HIDDEN_SAVE', 'HIDDEN_TRIGGER', 'TRIGGER_BUSINESS_EVENTS'
      ],
      excludeInTable: ['WIDTH']
    }
  },
  client: {
    mobile: {
      widget: {
        editor: {
          config: [
            'INFO', 'LABEL', 'FIELD_CODE', 'WIDTH', 'FORM_CUSTOM_COMPONENT_AI_IMAGE_COMPARE_SETTING',
            'FORMULA_RULE', 'HIDDEN', 'READONLY', 'REQUIRED', 'EDITONNEW',
            'UNIQUE', 'HIDDEN_SAVE', 'HIDDEN_TRIGGER', 'TRIGGER_BUSINESS_EVENTS'
          ],
          excludeInTable: ['WIDTH']
        }
      },
      component: {
        ide: 'MobileFormComponentAiImageCompareIde', edit: 'MobileFormComponentAiImageCompareEdit',
        read: 'MobileFormComponentAiImageCompareRead', list: 'MobileFormComponentAiImageCompareList',
        association: 'MobileFormComponentAiImageCompareAssociation', lov: 'MobileFormComponentAiImageCompareLov',
        tableColumn: 'MobileFormComponentAiImageCompareTableColumn'
      }
    }
  },
  methods: {},
  formatValueSchema: {}
}

export default config

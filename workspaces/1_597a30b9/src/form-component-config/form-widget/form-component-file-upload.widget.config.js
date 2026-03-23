const config = {
  version: 2.0,
  code: 'FORM_CUSTOM_COMPONENT_FILE_UPLOAD',
  desc: {
    iconType: 'DEFAULT',
    icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4" fill="#409EFF"/><path d="M12 14c-4 0-8 2-8 4v2h16v-2c0-2-4-4-8-4z" fill="#409EFF"/></svg>',
    text: '头像上传',
    description: '头像上传组件，支持裁剪和预览'
  },
  instance: { uuid: '$itemUuid', inTable: false },
  component: {
    ide: 'FormComponentFileUploadIde',
    edit: 'FormComponentFileUploadEdit',
    read: 'FormComponentFileUploadRead',
    list: 'FormComponentFileUploadList',
    association: 'FormComponentFileUploadList',
    lov: 'FormComponentFileUploadList',
    print: 'FormComponentFileUploadPrint',
    search: 'FormComponentFileUploadSearch',
    searchIde: 'FormComponentFileUploadSearchIde'
  },
  widget: {
    display: {
      label: '头像上传',
      width: 6,
      mobileWidth: 12,
      height: 1,
      hidden: false,
      readOnly: false,
      required: false,
      onlyCreateEdit: false
    },
    allow: { useInTableColumn: true },
    default: { customDefaultKey: 'defaultValue', value: '' },
    validator: { uniqueCheck: false },
    validatorList: [{ validatorConfig: [], validatorMessage: '' }],
    special: { frontBusinessObjectComponentType: 'BOF_TEXT', saveWithHidden: false },
    customComponentConfig: {},
    componentModelField: ['TEXT'],
    editor: {
      config: [
        'INFO', 'LABEL', 'FIELD_CODE', 'TITLE_DESCRIPTION', 'WIDTH',
        'FORM_CUSTOM_COMPONENT_FILE_UPLOAD_SETTING',
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
            'INFO', 'LABEL', 'FIELD_CODE', 'WIDTH', 'FORM_CUSTOM_COMPONENT_FILE_UPLOAD_SETTING',
            'FORMULA_RULE', 'HIDDEN', 'READONLY', 'REQUIRED', 'EDITONNEW',
            'UNIQUE', 'HIDDEN_SAVE', 'HIDDEN_TRIGGER', 'TRIGGER_BUSINESS_EVENTS'
          ],
          excludeInTable: ['WIDTH']
        }
      },
      component: {
        ide: 'MobileFormComponentFileUploadIde',
        edit: 'MobileFormComponentFileUploadEdit',
        read: 'MobileFormComponentFileUploadRead',
        list: 'MobileFormComponentFileUploadList',
        association: 'MobileFormComponentFileUploadAssociation',
        lov: 'MobileFormComponentFileUploadLov',
        tableColumn: 'MobileFormComponentFileUploadTableColumn'
      }
    }
  },
  methods: {},
  formatValueSchema: {}
}

export default config

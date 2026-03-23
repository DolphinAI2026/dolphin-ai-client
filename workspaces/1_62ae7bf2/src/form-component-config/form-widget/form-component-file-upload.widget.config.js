const config = {
  version: 2.0,
  code: 'FORM_CUSTOM_COMPONENT_FILE_UPLOAD',
  desc: {
    iconType: 'DEFAULT',
    icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" fill="#67C23A"/><path d="M7 14l3-3 2 2 4-4" stroke="#fff" stroke-width="2" fill="none"/><circle cx="17" cy="7" r="4" fill="#E6A23C"/></svg>',
    text: '物料拍照验收',
    description: '现场物料照片上传与AI图像识别，验证执行真实性'
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
      label: '物料拍照验收', width: 6, mobileWidth: 12, height: 1,
      hidden: false, readOnly: false, required: false, onlyCreateEdit: false
    },
    allow: { useInTableColumn: true },
    default: { customDefaultKey: 'defaultValue', value: '' },
    validator: { uniqueCheck: false },
    validatorList: [{ validatorConfig: [], validatorMessage: '' }],
    special: { frontBusinessObjectComponentType: 'BOF_TEXT', saveWithHidden: false },
    customComponentConfig: {
      enableAI: true,              // 是否启用AI识别
      aiModel: 'general',          // AI模型: general(通用)/materials(建材专用)
      quoteFormId: '',            // 报价单表单ID
      materialNameField: '',      // 物料名称字段
      quantityField: '',          // 预计数量字段
      matchThreshold: 0.8,         // 匹配阈值 0-1
      maxPhotoCount: 10,          // 最大照片数量
      autoRecognize: false        // 上传后自动识别
    },
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
        ide: 'MobileFormComponentFileUploadIde', edit: 'MobileFormComponentFileUploadEdit',
        read: 'MobileFormComponentFileUploadRead', list: 'MobileFormComponentFileUploadList',
        association: 'MobileFormComponentFileUploadAssociation', lov: 'MobileFormComponentFileUploadLov',
        tableColumn: 'MobileFormComponentFileUploadTableColumn'
      }
    }
  },
  methods: {},
  formatValueSchema: {}
}

export default config

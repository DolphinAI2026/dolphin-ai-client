const config = {
  version: 2.0,
  code: 'FORM_CUSTOM_COMPONENT_FILE_UPLOAD',
  desc: {
    iconType: 'DEFAULT',
    icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" fill="#67C23A"/><path d="M8 12l3 3 5-6" stroke="#fff" stroke-width="2" fill="none"/><circle cx="17" cy="7" r="4" fill="#E6A23C"/></svg>',
    text: 'AI图片识别',
    description: 'AI图片识别组件：支持摄像头/文件上传，AI智能分析图片，输出通过/不通过建议'
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
      label: 'AI图片识别', width: 6, mobileWidth: 12, height: 2,
      hidden: false, readOnly: false, required: false, onlyCreateEdit: false
    },
    allow: { useInTableColumn: true },
    default: { customDefaultKey: 'defaultValue', value: '' },
    validator: { uniqueCheck: false },
    validatorList: [{ validatorConfig: [], validatorMessage: '' }],
    special: { frontBusinessObjectComponentType: 'BOF_TEXT', saveWithHidden: false },
    customComponentConfig: {
      // AI配置
      aiApiUrl: '',           // AI接口地址
      aiApiKey: '',           // AI接口密钥
      aiPrompt: '请分析这张图片，判断是否合格。如果合格返回"通过"，如果不合格返回"不通过"并说明原因。', // AI提示词
      resultField: '',        // 结果字段映射（通过/不通过）
      reasonField: '',        // 原因字段映射
      confidenceThreshold: 0.8, // 置信度阈值
      enableCamera: true,     // 启用摄像头
      enableFileUpload: true, // 启用文件上传
      maxImageSize: 5,        // 最大图片大小(MB)
      acceptedFormats: ['jpg', 'jpeg', 'png', 'bmp', 'webp'] // 接受的格式
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

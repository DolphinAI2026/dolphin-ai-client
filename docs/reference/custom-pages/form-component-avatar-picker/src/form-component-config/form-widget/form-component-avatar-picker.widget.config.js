const FormComponentAvatarPickerWidgetConfig = {
  version: 2.0,
  code: 'FORM_CUSTOM_COMPONENT_AVATAR_PICKER',
  desc: {
    iconType: 'DEFAULT',
    // 人员头像：用户图标 + 圆形头像风格
    icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4" fill="#409EFF"/><path d="M4 20c0-4.4 3.6-8 8-8s8 3.6 8 8" fill="#409EFF" opacity="0.6"/><circle cx="18" cy="6" r="3" fill="#67C23A"/><path d="M16.5 6h3M18 4.5v3" stroke="#fff" stroke-width="1" stroke-linecap="round"/></svg>',
    text: '人员头像',
    description: '人员头像选择组件，支持展示用户头像和选择人员'
  },
  instance: {
    uuid: '$itemUuid',
    inTable: false
  },
  component: {
    ide: 'FormComponentAvatarPickerIde',
    edit: 'FormComponentAvatarPickerEdit',
    read: 'FormComponentAvatarPickerRead',
    list: 'FormComponentAvatarPickerList',
    association: 'FormComponentAvatarPickerList',
    lov: 'FormComponentAvatarPickerList',
    print: 'FormComponentAvatarPickerPrint',
    search: 'FormComponentAvatarPickerSearch',
    searchIde: 'FormComponentAvatarPickerSearchIde'
  },
  widget: {
    display: {
      label: '人员头像',
      width: 6,
      mobileWidth: 12,
      height: 1,
      hidden: false,
      readOnly: false,
      required: false,
      onlyCreateEdit: false
    },
    allow: {
      useInTableColumn: true
    },
    default: {
      customDefaultKey: 'defaultValue',
      value: ''
    },
    validator: {
      uniqueCheck: false
    },
    validatorList: [
      {
        validatorConfig: [],
        validatorMessage: ''
      }
    ],
    special: {
      frontBusinessObjectComponentType: 'BOF_TEXT',
      saveWithHidden: false
    },
    editor: {
      config: [
        'INFO',
        'LABEL',
        'FIELD_CODE',
        'TITLE_DESCRIPTION',
        'WIDTH',
        'FORM_CUSTOM_COMPONENT_AVATAR_PICKER_SETTING',
        'FORMULA_RULE',
        'HIDDEN',
        'READONLY',
        'REQUIRED',
        'EDITONNEW',
        'UNIQUE',
        'HIDDEN_SAVE',
        'HIDDEN_TRIGGER',
        'TRIGGER_BUSINESS_EVENTS'
      ],
      excludeInTable: ['WIDTH']
    }
  },
  componentModelField: ['STRING'],
  client: {
    mobile: {
      widget: {
        editor: {
          config: [
            'INFO',
            'LABEL',
            'FIELD_CODE',
            'WIDTH',
            'FORM_CUSTOM_COMPONENT_AVATAR_PICKER_SETTING',
            'FORMULA_RULE',
            'HIDDEN',
            'READONLY',
            'REQUIRED',
            'EDITONNEW',
            'UNIQUE',
            'HIDDEN_SAVE',
            'HIDDEN_TRIGGER',
            'TRIGGER_BUSINESS_EVENTS'
          ],
          excludeInTable: ['WIDTH']
        }
      },
      component: {
        ide: 'MobileFormComponentAvatarPickerIde',
        edit: 'MobileFormComponentAvatarPickerEdit',
        read: 'MobileFormComponentAvatarPickerRead',
        list: 'MobileFormComponentAvatarPickerList',
        association: 'MobileFormComponentAvatarPickerAssociation',
        lov: 'MobileFormComponentAvatarPickerLov',
        tableColumn: 'MobileFormComponentAvatarPickerTableColumn'
      }
    }
  },
  methods: {},
  formatValueSchema: {}
}

export default FormComponentAvatarPickerWidgetConfig

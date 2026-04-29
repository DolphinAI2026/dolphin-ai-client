const FormComponentSupplierNetworkWidgetConfig = {
  version: 2.0,
  code: 'FORM_CUSTOM_COMPONENT_SUPPLIER_NETWORK',
  desc: {
    iconType: 'DEFAULT',
    icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="6" r="3" fill="#409EFF"/><circle cx="5" cy="18" r="3" fill="#67C23A"/><circle cx="19" cy="18" r="3" fill="#E6A23C"/><line x1="12" y1="9" x2="5" y2="15" stroke="#409EFF" stroke-width="1.5" opacity="0.6"/><line x1="12" y1="9" x2="19" y2="15" stroke="#409EFF" stroke-width="1.5" opacity="0.6"/><line x1="8" y1="18" x2="16" y2="18" stroke="#409EFF" stroke-width="1.5" opacity="0.6"/></svg>',
    text: '供应商网络图',
    description: '供应商关系网络可视化组件，支持力导向关系图和多维度数据汇总看板'
  },
  instance: {
    uuid: '$itemUuid',
    inTable: false
  },
  component: {
    ide: 'FormComponentSupplierNetworkIde',
    edit: 'FormComponentSupplierNetworkEdit',
    read: 'FormComponentSupplierNetworkRead',
    list: 'FormComponentSupplierNetworkList',
    association: 'FormComponentSupplierNetworkList',
    lov: 'FormComponentSupplierNetworkList',
    print: 'FormComponentSupplierNetworkPrint',
    search: 'FormComponentSupplierNetworkSearch',
    searchIde: 'FormComponentSupplierNetworkSearchIde'
  },
  widget: {
    display: {
      label: '供应商网络图',
      width: 12,
      mobileWidth: 12,
      height: 3,
      hidden: false,
      readOnly: false,
      required: false,
      onlyCreateEdit: false
    },
    allow: {
      useInTableColumn: false
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
    componentModelField: ['TEXT'],
    editor: {
      config: [
        'INFO',
        'LABEL',
        'FIELD_CODE',
        'TITLE_DESCRIPTION',
        'WIDTH',
        'FORM_CUSTOM_COMPONENT_SUPPLIER_NETWORK_SETTING',
        'FORMULA_RULE',
        'HIDDEN',
        'READONLY',
        'HIDDEN_SAVE',
        'HIDDEN_TRIGGER',
        'TRIGGER_BUSINESS_EVENTS'
      ],
      excludeInTable: ['WIDTH']
    }
  },
  client: {
    mobile: {
      widget: {
        editor: {
          config: [
            'INFO',
            'LABEL',
            'FIELD_CODE',
            'WIDTH',
            'FORM_CUSTOM_COMPONENT_SUPPLIER_NETWORK_SETTING',
            'FORMULA_RULE',
            'HIDDEN',
            'READONLY',
            'HIDDEN_SAVE',
            'HIDDEN_TRIGGER',
            'TRIGGER_BUSINESS_EVENTS'
          ],
          excludeInTable: ['WIDTH']
        }
      },
      component: {
        ide: 'MobileFormComponentSupplierNetworkIde',
        edit: 'MobileFormComponentSupplierNetworkEdit',
        read: 'MobileFormComponentSupplierNetworkRead',
        list: 'MobileFormComponentSupplierNetworkList',
        association: 'MobileFormComponentSupplierNetworkAssociation',
        lov: 'MobileFormComponentSupplierNetworkLov',
        tableColumn: 'MobileFormComponentSupplierNetworkTableColumn'
      }
    }
  },
  methods: {},
  formatValueSchema: {}
}

export default FormComponentSupplierNetworkWidgetConfig

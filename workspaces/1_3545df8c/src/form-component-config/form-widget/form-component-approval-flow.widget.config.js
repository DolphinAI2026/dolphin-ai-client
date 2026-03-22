const config = {
  version: 2.0,
  code: 'FORM_CUSTOM_COMPONENT_APPROVAL_FLOW',
  desc: {
    iconType: 'DEFAULT',
    icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" fill="#409EFF"/><text x="12" y="16" text-anchor="middle" fill="#fff" font-size="10">C</text></svg>',
    text: 'approval-flow',
    description: 'approval-flow'
  },
  instance: { uuid: '$itemUuid', inTable: false },
  component: {
    ide: 'FormComponentApprovalFlowIde',
    edit: 'FormComponentApprovalFlowEdit',
    read: 'FormComponentApprovalFlowRead',
    list: 'FormComponentApprovalFlowList',
    association: 'FormComponentApprovalFlowList',
    lov: 'FormComponentApprovalFlowList',
    print: 'FormComponentApprovalFlowPrint',
    search: 'FormComponentApprovalFlowSearch',
    searchIde: 'FormComponentApprovalFlowSearchIde'
  },
  widget: {
    display: {
      label: 'approval-flow', width: 6, mobileWidth: 12, height: 1,
      hidden: false, readOnly: false, required: false, onlyCreateEdit: false
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
        'FORM_CUSTOM_COMPONENT_APPROVAL_FLOW_SETTING',
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
            'INFO', 'LABEL', 'FIELD_CODE', 'WIDTH', 'FORM_CUSTOM_COMPONENT_APPROVAL_FLOW_SETTING',
            'FORMULA_RULE', 'HIDDEN', 'READONLY', 'REQUIRED', 'EDITONNEW',
            'UNIQUE', 'HIDDEN_SAVE', 'HIDDEN_TRIGGER', 'TRIGGER_BUSINESS_EVENTS'
          ],
          excludeInTable: ['WIDTH']
        }
      },
      component: {
        ide: 'MobileFormComponentApprovalFlowIde', edit: 'MobileFormComponentApprovalFlowEdit',
        read: 'MobileFormComponentApprovalFlowRead', list: 'MobileFormComponentApprovalFlowList',
        association: 'MobileFormComponentApprovalFlowAssociation', lov: 'MobileFormComponentApprovalFlowLov',
        tableColumn: 'MobileFormComponentApprovalFlowTableColumn'
      }
    }
  },
  methods: {},
  formatValueSchema: {}
}

export default config

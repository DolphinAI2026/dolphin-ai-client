const config = {
  version: 2.0,
  code: 'FORM_CUSTOM_COMPONENT_STAR_RATING',
  desc: {
    iconType: 'DEFAULT',
    icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" fill="#409EFF"/><text x="12" y="16" text-anchor="middle" fill="#fff" font-size="10">C</text></svg>',
    text: 'star-rating',
    description: 'star-rating'
  },
  instance: { uuid: '$itemUuid', inTable: false },
  component: {
    ide: 'FormComponentStarRatingIde',
    edit: 'FormComponentStarRatingEdit',
    read: 'FormComponentStarRatingRead',
    list: 'FormComponentStarRatingList',
    association: 'FormComponentStarRatingList',
    lov: 'FormComponentStarRatingList',
    print: 'FormComponentStarRatingPrint',
    search: 'FormComponentStarRatingSearch',
    searchIde: 'FormComponentStarRatingSearchIde'
  },
  widget: {
    display: {
      label: 'star-rating', width: 6, mobileWidth: 12, height: 1,
      hidden: false, readOnly: false, required: false, onlyCreateEdit: false
    },
    allow: { useInTableColumn: true },
    default: { customDefaultKey: 'defaultValue', value: '' },
    validator: { uniqueCheck: false },
    validatorList: [{ validatorConfig: [], validatorMessage: '' }],
    special: { frontBusinessObjectComponentType: 'BOF_TEXT', saveWithHidden: false },
    customComponentConfig: {
      maxStars: 5,
      allowHalf: true,
      activeColor: '#FF9900',
      inactiveColor: '#E0E0E0',
      size: 'medium',
      showText: false,
      texts: ['极差', '差', '一般', '良好', '优秀']
    },
    componentModelField: ['TEXT'],
    editor: {
      config: [
        'INFO', 'LABEL', 'FIELD_CODE', 'TITLE_DESCRIPTION', 'WIDTH',
        'FORM_CUSTOM_COMPONENT_STAR_RATING_SETTING',
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
            'INFO', 'LABEL', 'FIELD_CODE', 'WIDTH', 'FORM_CUSTOM_COMPONENT_STAR_RATING_SETTING',
            'FORMULA_RULE', 'HIDDEN', 'READONLY', 'REQUIRED', 'EDITONNEW',
            'UNIQUE', 'HIDDEN_SAVE', 'HIDDEN_TRIGGER', 'TRIGGER_BUSINESS_EVENTS'
          ],
          excludeInTable: ['WIDTH']
        }
      },
      component: {
        ide: 'MobileFormComponentStarRatingIde', edit: 'MobileFormComponentStarRatingEdit',
        read: 'MobileFormComponentStarRatingRead', list: 'MobileFormComponentStarRatingList',
        association: 'MobileFormComponentStarRatingAssociation', lov: 'MobileFormComponentStarRatingLov',
        tableColumn: 'MobileFormComponentStarRatingTableColumn'
      }
    }
  },
  methods: {},
  formatValueSchema: {}
}

export default config

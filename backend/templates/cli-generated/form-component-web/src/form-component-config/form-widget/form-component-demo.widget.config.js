const FormComponentDemoWidgetConfig = {
  version: 2.0, // 组件版本
  code: 'FORM_CUSTOM_COMPONENT_DEMO', // 组件编码
  desc: { // 组件描述信息
    iconType: 'DEFAULT', // 组件icon类型
    icon: 'form-custom-widget', // 组件svg图标名称
    // 组件名称
    text: 'demo',
    // 组件具体描述
    description: 'demo component'
  },
  // 组件实例参数
  instance: {
    uuid: '$itemUuid',
    inTable: false
  },
  // 在不同地方渲染的Vue组件的name
  component: {
    ide: 'FormComponentDemoIde', // 在表单设计状态下使用的组件
    edit: 'FormComponentDemoEdit', // 在可编辑（弹窗）状态下使用的组件
    read: 'FormComponentDemoRead', // 在查看（抽屉）状态下使用的组件
    list: 'FormComponentDemoList', // 在前台列表的表格上显示的组件
    association: 'FormComponentDemoAssociation', // 在关联表单的表格上显示的组件
    lov: 'FormComponentDemoLov', // 在数据选择弹窗的表格上显示的组件
    print: 'FormComponentDemoPrint', // 在系统打印中显示的组件
    search: 'FormComponentDemoSearch', // 在前台列表查询面板上显示的组件
    searchIde: 'FormComponentDemoSearchIde' // 在后台列表设计中查询面板显示的组件
  },
  // 组件配置以及组件配置的默认值
  widget: {
    // 控制组件展示的这类配置的默认值
    display: {
      // 组件标题名称默认值
      label: 'demo',
      width: 6, // 组件宽带默认值
      mobileWidth: 12, // 组件移动端宽带默认值
      height: 1, // 组件高度默认值
      hidden: false, // 组件是否隐藏默认值
      readOnly: false, // 组件是否只读默认值
      required: false, // 组件是否必填默认值
      onlyCreateEdit: false // 是否只仅新建可编辑默认值
    },
    // 控制组件是否被允许进行某些操作的这类配置的默认值
    allow: {
      // calcRule: false,
      useInTableColumn: true // 组件是否允许在表格列中使用
      // scanCode: false
    },
    // 控制组件的默认值的这类配置的默认值
    default: {
      customDefaultKey: 'defaultValue', // 默认值的key
      value: '' // 默认值
    },
    // 控制组件校验规则的这类配置的默认值
    validator: {
      uniqueCheck: false, // 唯一性校验默认值
      numberMax: 5 // 数字最大值校验默认值
    },
    // 控制组件的特殊配置这类配置的默认值
    special: {
      frontBusinessObjectComponentType: 'BOF_TEXT', // 前端业务对象组件类型默认值
      saveWithHidden: false // 隐藏时是否保存
    },
    // 表单设计时组件的配置项
    editor: {
      // Web端表单设计，该组件所包含的所有配置code数组
      config: [
        'INFO', // 组件信息
        'LABEL', // 标题名称
        'FIELD_CODE', // 字段编码
        'TITLE_DESCRIPTION', // 标题说明
        'WIDTH', // 宽度
        'FORM_CUSTOM_COMPONENT_DEMO_SETTING', // 自定义组件设置
        'FORMULA_RULE', // 公式规则
        'HIDDEN', // 是否隐藏
        'READONLY', // 是否只读
        'REQUIRED', // 是否必填
        'EDITONNEW', // 仅新建可编辑
        'UNIQUE', // 唯一性校验
        'HIDDEN_SAVE', // 隐藏时提交
        'HIDDEN_TRIGGER', // 隐藏时触发
        'TRIGGER_BUSINESS_EVENTS' // 触发业务事件
      ],
      // 如果组件拖入到子表内，需要排除的配置code数组
      excludeInTable: ['WIDTH'] // 将宽度排除
    }
  },
  // 不同客户端的相关配置
  client: {
    // 移动端配置
    mobile: {
      // 组件配置
      widget: {
        // 表单设计时组件的配置项
        editor: {
          // 移动端表单设计，该组件所包含的所有配置code数组
          config: [
            'INFO', // 组件信息
            'LABEL', // 标题名称
            'FIELD_CODE', // 字段编码
            'WIDTH', // 宽度
            'FORM_CUSTOM_COMPONENT_DEMO_SETTING', // 自定义组件设置
            'FORMULA_RULE', // 公式规则
            'HIDDEN', // 是否隐藏
            'READONLY', // 是否只读
            'REQUIRED', // 是否必填
            'EDITONNEW', // 仅新建可编辑
            'UNIQUE', // 唯一性校验
            'HIDDEN_SAVE', // 隐藏时提交
            'HIDDEN_TRIGGER', // 隐藏时触发
            'TRIGGER_BUSINESS_EVENTS' // 触发业务事件
          ],
          // 如果组件拖入到子表内，需要排除的配置code数组
          excludeInTable: ['WIDTH']  // 将宽度排除
        }
      },
      // 在不同地方渲染的Vue组件的name
      component: {
        ide: 'MobileFormComponentDemoIde', // 在表单设计状态下使用的组件
        edit: 'MobileFormComponentDemoEdit', // 在可编辑（弹窗）状态下使用的组件
        read: 'MobileFormComponentDemoRead', // 在查看（抽屉）状态下使用的组件
        list: 'MobileFormComponentDemoList', // 在前台列表的表格上显示的组件
        association: 'MobileFormComponentDemoAssociation', // 在关联表单的表格上显示的组件
        lov: 'MobileFormComponentDemoLov', // 在数据选择弹窗的表格上显示的组件
        tableColumn: 'MobileFormComponentDemoTableColumn' // 在子表组件的卡片上和表格上显示的组件
      }
    }
  },
  methods: {

  },
  formatValueSchema: {
    
  },
}

export default FormComponentDemoWidgetConfig

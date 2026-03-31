// eslint-disable-next-line
const AbilityControl = window.df.getVue().constructor.FormEngine.AbilityControl

export default {
  // BOF_TEXT: {
  //   // FORM_CUSTOM_RATE 如何赋值给 BOF_TEXT
  //   FORM_CUSTOM_RATE: {
  //     // DEFUALT 为默认的转换方式
  //     DEFUALT: {
  //       /**
  //        * 转换方法
  //        * @param {*} value 原始值
  //        * @param {*} sourceComponentConfig 源组件配置
  //        * @param {*} targetComponentConfig 目标组件配置
  //        * @returns 转换后的值
  //        */
  //       value: (value, sourceComponentConfig, targetComponentConfig) => {
  //         return value + '分'
  //       }
  //     },
  //     // <AbilityCode> 为特殊能力编码的转换方式，如 AbilityControl.ASSOCIATION_FORM_ASSOCIATE_FIELD
  //     // 该方式会覆盖 DEFUALT 的转换方式，即 在这个 AbilityControl.ASSOCIATION_FORM_ASSOCIATE_FIELD的情况下，执行的转换方式
  //     // '<AbilityCode>': {
  //     //   value: (value, sourceComponentConfig, targetComponentConfig) => {
  //     //     return xxxxxx
  //     //   }
  //     // }
  //   }
  // }
}
const i18n = window.df && window.df.getI18n()

const WidgetAreaRequiredValidator = (errorMsg, uuid, xid) => {
  return (rule, widget, value, callback) => {
    if (!value) {
      return callback(
        new Error(`${widget.label}${errorMsg}`, uuid, xid)
      )
    }
    if (!value.province || !value.province.code || !value.province.name) {
      return callback(
        new Error(`${widget.label}${errorMsg}`), uuid, xid
      )
    }
    return callback()
  }
}

const WidgetAreaLevelRangeValidator = (errorMsg, uuid, xid, widget) => {
  return (rule, value, callback) => {
    if (!value) {
      return callback()
    }
    const { areaLevelRange } = widget
    const { length: currLevel } = Object.values(value).filter(item => item.name)
    // 无限制情况
    if (areaLevelRange === 'UNSET') {
      return callback()
    }
    // 空值情况
    if (!currLevel) {
      return callback()
    }
    const level = {
      'PROVINCE': 1,
      'AREA_PROVINCE_CITY': 2,
      'AREA': 3,
      'AREA_ADDRESS': 4
    }
    const levelI18n = [
      i18n.t('formConfig.areaType.province'),
      i18n.t('formConfig.areaType.city'),
      i18n.t('formConfig.areaType.areas'),
      i18n.t('formConfig.areaType.address')
    ]
    const needLevel = level[areaLevelRange]
    // 详细地址特殊情况情况
    if (
      needLevel === 4 &&
      value &&
      value.address &&
      value.address.name &&
      !value.area.code
    ) {
      return callback(
        new Error(`${levelI18n[2]}${errorMsg}`), uuid, xid
      )
    }
    if (needLevel === currLevel) {
      if (
        currLevel === 1 &&
        value &&
        value.address &&
        value.address.name
      ) {
        return callback(
          new Error(`${levelI18n[0]}${errorMsg}`), uuid, xid
        )
      }
      return callback()
    } else if (needLevel > currLevel) {
      // 旧版样式从前往后校验，新版样式从后往前校验
      const themeType = document.body.className.includes('ORIGIN')
      return callback(
        new Error(`${levelI18n[themeType ? currLevel : (needLevel - 1)]}${errorMsg}`), uuid, xid
      )
    }
    return callback()
  }
}

export { WidgetAreaRequiredValidator, WidgetAreaLevelRangeValidator }

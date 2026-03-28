import { WidgetAreaRequiredValidator } from './widget-area-validator'
const WidgetRequiredValidator = (errorMsg, uuid, xid, widget) => {
  return (rule, value, callback) => {
    if (widget && widget.componentType === 'FORM_WIDGET_AREA') {
      return WidgetAreaRequiredValidator(errorMsg, uuid, xid)('', widget, value, callback)
    } else {
      if (value === undefined || value === null) {
        return callback(new Error(errorMsg), uuid, xid)
      }
      if (Array.isArray(value) && !value.length) {
        return callback(new Error(errorMsg), uuid, xid)
      }
      if (typeof value === 'string' && !value) {
        return callback(new Error(errorMsg), uuid, xid)
      }
      if (typeof value === 'object' && JSON.stringify(value) === '{}') {
        return callback(new Error(errorMsg), uuid, xid)
      }
      return callback()
    }
  }
}

export default WidgetRequiredValidator

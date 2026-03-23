const WidgetAreaRequiredValidator = (errorMsg, uuid, xid) => {
  return (rule, widget, value, callback) => {
    if (!value) return callback(new Error(errorMsg), uuid, xid)
    if (!value.province || !value.province.code) return callback(new Error(errorMsg), uuid, xid)
    return callback()
  }
}
export { WidgetAreaRequiredValidator }

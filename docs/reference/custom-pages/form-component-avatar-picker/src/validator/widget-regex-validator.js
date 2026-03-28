const WidgetRegexValidator = (regex, errorMsg) => {
  let reg
  try {
    reg = new RegExp(regex)
  } catch (e) {
    console.log(e)
  }
  if (!reg) {
    return
  }
  return (rule, value, callback) => {
    if (value && !reg.test(value)) {
      callback(new Error(errorMsg))
    } else {
      callback()
    }
  }
}

export default WidgetRegexValidator

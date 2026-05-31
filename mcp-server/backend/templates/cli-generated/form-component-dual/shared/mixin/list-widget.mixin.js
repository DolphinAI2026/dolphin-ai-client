const ListWidgetMixin = {
  inject: ["listEngine"],
  props: {
    componentConfig: {
      required: true,
      type: Object
    },
    formValue: {
      required: true,
      type: Object
    },
    propKey: {
      required: true,
      type: String
    }
  }
}
export default ListWidgetMixin

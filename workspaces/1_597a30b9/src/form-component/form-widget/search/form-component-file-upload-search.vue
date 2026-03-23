<template>
  <div class="form-widget form-component-avatar-upload-search">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
    >
      <el-input
        v-model="searchValue"
        clearable
        size="mini"
        placeholder="输入头像URL搜索"
        @change="handleSearchChange"
      />
    </x-proxy-form-item>
  </div>
</template>

<script>
import SearchWidgetMixin from '@/mixin/search-widget.mixin'

export default {
  name: 'FormComponentFileUploadSearch',
  mixins: [SearchWidgetMixin],
  computed: {
    searchValue: {
      get() { return this.formValue },
      set(val) { this.formValue = val }
    }
  },
  methods: {
    handleSearchChange(val) {
      // 头像搜索场景：支持按URL模糊匹配
      this.$emit('formEventEmit', {
        eventName: 'search',
        propKey: this.propKey,
        event: val,
        widget: this.widget
      })
    }
  }
}
</script>

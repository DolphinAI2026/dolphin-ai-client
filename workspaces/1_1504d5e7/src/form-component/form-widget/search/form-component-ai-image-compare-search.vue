<template>
  <div class="form-widget form-component-screenshot-search">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <el-input v-model="searchValue" clearable size="mini" placeholder="输入截图附件ID搜索">
        <template slot="prefix">
          <i class="el-icon-picture-outline-round"></i>
        </template>
      </el-input>
    </x-proxy-form-item>
  </div>
</template>
<script>
import SearchWidgetMixin from '@/mixin/search-widget.mixin'
export default {
  name: 'FormComponentAiImageCompareSearch',
  mixins: [SearchWidgetMixin],
  computed: {
    searchValue: {
      get() { return this.formValue },
      set(val) { this.formValue = val }
    }
  }
}
</script>

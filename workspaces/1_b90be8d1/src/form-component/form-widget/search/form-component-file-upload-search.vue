<template>
  <div class="form-widget ai-image-recognition-search">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <el-input v-model="searchValue" clearable size="mini" placeholder="请输入图片描述关键词搜索">
        <i slot="prefix" class="el-icon-picture-outline"></i>
      </el-input>
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
  }
}
</script>

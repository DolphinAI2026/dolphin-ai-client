<template>
  <div class="form-widget form-component-screenshot-list">
    <span v-if="formValue" class="screenshot-indicator">
      <i class="el-icon-picture-outline-round"></i>
      <span>截图</span>
    </span>
    <span v-else>-</span>
  </div>
</template>

<script>
export default {
  name: 'FormComponentAiImageCompareList',
  props: {
    componentConfig: { type: Object, default() { return {} } },
    formValue: { type: [String, Object, Array], default: '' },
    propKey: { type: String, default: '' }
  }
}
</script>

<style lang="scss">
.form-component-screenshot-list {
  .screenshot-indicator {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    background: #f0f9eb;
    color: #67c23a;
    border-radius: 4px;
    font-size: 12px;

    i {
      font-size: 14px;
    }
  }
}
</style>

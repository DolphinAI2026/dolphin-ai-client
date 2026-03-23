<template>
  <div class="form-widget ai-image-recognition-list">
    <div v-if="displayValue.imageUrl" class="list-preview">
      <img :src="displayValue.imageUrl" alt="图片" class="list-image">
      <span v-if="displayValue.analysisResult" class="result-tag" :class="displayValue.analysisResult.result">
        {{ displayValue.analysisResult.result === 'pass' ? '通过' : '不通过' }}
      </span>
    </div>
    <span v-else>-</span>
  </div>
</template>

<script>
export default {
  name: 'FormComponentFileUploadList',
  props: {
    componentConfig: { type: Object, default() { return {} } },
    formValue: { type: [String, Object, Array], default: '' },
    propKey: { type: String, default: '' }
  },
  computed: {
    displayValue() {
      if (!this.formValue) return {}
      if (typeof this.formValue === 'string') {
        try {
          return JSON.parse(this.formValue)
        } catch {
          return { imageUrl: this.formValue }
        }
      }
      return this.formValue
    }
  }
}
</script>

<style lang="scss" scoped>
.ai-image-recognition-list {
  .list-preview {
    display: flex;
    align-items: center;
    gap: 6px;

    .list-image {
      width: 40px;
      height: 40px;
      object-fit: cover;
      border-radius: 4px;
      border: 1px solid #ebeef5;
    }

    .result-tag {
      font-size: 11px;
      padding: 2px 6px;
      border-radius: 8px;

      &.pass {
        background: #67c23a;
        color: #fff;
      }

      &.fail {
        background: #f56c6c;
        color: #fff;
      }
    }
  }
}
</style>

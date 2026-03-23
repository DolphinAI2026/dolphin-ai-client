<template>
  <div class="form-widget ai-image-recognition-print">
    <div v-if="printValue.imageUrl" class="print-content">
      <img :src="printValue.imageUrl" alt="图片" class="print-image">
      <div v-if="printValue.analysisResult" class="print-result">
        <span class="result-label">AI分析结果：</span>
        <span class="result-value" :class="printValue.analysisResult.result">
          {{ printValue.analysisResult.result === 'pass' ? '通过' : '不通过' }}
        </span>
        <span v-if="printValue.analysisResult.reason" class="result-reason">
          {{ printValue.analysisResult.reason }}
        </span>
      </div>
    </div>
    <span v-else>-</span>
  </div>
</template>

<script>
import PrintWidgetMixin from '@/mixin/print-widget.mixin'

export default {
  name: 'FormComponentFileUploadPrint',
  mixins: [PrintWidgetMixin],
  computed: {
    printValue() {
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
.ai-image-recognition-print {
  .print-content {
    .print-image {
      max-width: 200px;
      max-height: 150px;
      border: 1px solid #ebeef5;
      margin-bottom: 8px;
    }

    .print-result {
      .result-label {
        font-weight: bold;
      }

      .result-value {
        font-weight: bold;

        &.pass {
          color: #67c23a;
        }

        &.fail {
          color: #f56c6c;
        }
      }

      .result-reason {
        display: block;
        margin-top: 4px;
        font-size: 12px;
        color: #606266;
      }
    }
  }
}
</style>

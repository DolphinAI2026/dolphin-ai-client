<template>
  <div class="form-widget ai-image-recognition-read">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div class="ai-image-recognition-display" v-if="displayValue.imageUrl">
        <div class="image-preview">
          <img :src="displayValue.imageUrl" alt="图片">
          <div v-if="displayValue.analysisResult" class="result-badge" :class="displayValue.analysisResult.result">
            <i :class="displayValue.analysisResult.result === 'pass' ? 'el-icon-success' : 'el-icon-error'"></i>
            <span>{{ displayValue.analysisResult.result === 'pass' ? '通过' : '不通过' }}</span>
          </div>
        </div>
        <div v-if="displayValue.analysisResult" class="result-info">
          <div v-if="displayValue.analysisResult.confidence" class="confidence">
            置信度：{{ (displayValue.analysisResult.confidence * 100).toFixed(1) }}%
          </div>
          <div v-if="displayValue.analysisResult.reason" class="reason">
            {{ displayValue.analysisResult.reason }}
          </div>
        </div>
      </div>
      <span v-else class="no-image">暂无图片</span>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentFileUploadRead',
  mixins: [FormWidgetMixin],
  computed: {
    displayValue() {
      const value = this.formValue
      if (!value) return {}
      if (typeof value === 'string') {
        try {
          return JSON.parse(value)
        } catch {
          return { imageUrl: value }
        }
      }
      return value
    }
  }
}
</script>

<style lang="scss" scoped>
.ai-image-recognition-read {
  .ai-image-recognition-display {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .image-preview {
    position: relative;
    display: inline-block;
    max-width: 200px;

    img {
      max-width: 100%;
      max-height: 150px;
      border-radius: 4px;
      border: 1px solid #ebeef5;
    }

    .result-badge {
      position: absolute;
      bottom: 8px;
      right: 8px;
      padding: 2px 8px;
      border-radius: 10px;
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 4px;

      &.pass {
        background: #67c23a;
        color: #fff;
      }

      &.fail {
        background: #f56c6c;
        color: #fff;
      }

      &.unknown {
        background: #909399;
        color: #fff;
      }
    }
  }

  .result-info {
    font-size: 13px;
    color: #606266;

    .confidence {
      margin-bottom: 2px;
    }

    .reason {
      line-height: 1.4;
    }
  }

  .no-image {
    color: #c0c4cc;
    font-size: 13px;
  }
}
</style>

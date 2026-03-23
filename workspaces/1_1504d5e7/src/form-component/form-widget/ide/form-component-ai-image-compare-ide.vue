<template>
  <div class="form-widget form-component-screenshot-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div class="screenshot-ide-preview">
        <div class="preview-icon">
          <i class="el-icon-scissors"></i>
        </div>
        <div class="preview-text">
          <span class="preview-label">{{ buttonText }}</span>
          <span class="preview-hint">点击进行截图</span>
        </div>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentAiImageCompareIde',
  mixins: [FormWidgetMixin],
  computed: {
    buttonText() {
      return this.widget.customComponentConfig?.buttonText || '截图'
    }
  }
}
</script>

<style lang="scss">
.form-component-screenshot-ide {
  .screenshot-ide-preview {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    background: #f5f7fa;
    border: 1px dashed #dcdfe6;
    border-radius: 4px;

    .preview-icon {
      width: 40px;
      height: 40px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #e8f4d9;
      border-radius: 8px;

      i {
        font-size: 20px;
        color: #67c23a;
      }
    }

    .preview-text {
      display: flex;
      flex-direction: column;
      gap: 2px;

      .preview-label {
        font-size: 14px;
        color: #303133;
        font-weight: 500;
      }

      .preview-hint {
        font-size: 12px;
        color: #909399;
      }
    }
  }
}
</style>

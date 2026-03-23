<template>
  <div class="form-widget ai-image-recognition-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div class="ide-preview">
        <div class="preview-card">
          <div class="preview-header">
            <i class="el-icon-picture-outline"></i>
            <span>AI图片识别</span>
          </div>
          <div class="preview-content">
            <div class="preview-upload">
              <i class="el-icon-upload2"></i>
              <span>点击上传图片</span>
            </div>
            <div class="preview-features">
              <span class="feature"><i class="el-icon-camera"></i> 摄像头</span>
              <span class="feature"><i class="el-icon-magic-stick"></i> AI分析</span>
            </div>
          </div>
        </div>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentFileUploadIde',
  mixins: [FormWidgetMixin]
}
</script>

<style lang="scss" scoped>
.ai-image-recognition-ide {
  .ide-preview {
    .preview-card {
      border: 1px dashed #409eff;
      border-radius: 6px;
      background: linear-gradient(135deg, #f0f9eb 0%, #ecf5ff 100%);
      padding: 12px;

      .preview-header {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
        color: #409eff;
        font-weight: 500;
        margin-bottom: 8px;

        i {
          font-size: 16px;
        }
      }

      .preview-content {
        .preview-upload {
          border: 1px dashed #dcdfe6;
          border-radius: 4px;
          padding: 16px;
          text-align: center;
          background: #fff;
          margin-bottom: 8px;

          i {
            font-size: 24px;
            color: #c0c4cc;
            display: block;
            margin-bottom: 4px;
          }

          span {
            font-size: 12px;
            color: #909399;
          }
        }

        .preview-features {
          display: flex;
          justify-content: center;
          gap: 8px;

          .feature {
            font-size: 11px;
            color: #606266;
            display: flex;
            align-items: center;
            gap: 2px;

            i {
              font-size: 12px;
              color: #67c23a;
            }
          }
        }
      }
    }
  }
}
</style>

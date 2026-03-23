<template>
  <div class="form-widget form-component-material-verify-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :titleDescription="widget.titleDescription"
      :renderScene="renderScene"
      :processTitle="widget.processTitle"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
      :webFormSettings="webFormSettings"
    >
      <div class="ide-preview">
        <div class="preview-card">
          <div class="preview-icon">
            <i class="el-icon-camera"></i>
          </div>
          <div class="preview-text">
            <span class="preview-title">物料拍照验收</span>
            <span class="preview-desc">上传现场照片，AI识别物料，与报价单比对</span>
          </div>
        </div>

        <div class="preview-tags">
          <el-tag size="mini" type="success" class="ml-2">
            <i class="el-icon-microphone"></i> AI识别
          </el-tag>
          <el-tag size="mini" type="warning" class="ml-2">
            <i class="el-icon-document"></i> 报价比对
          </el-tag>
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

<style lang="scss">
.form-component-material-verify-ide {
  .ide-preview {
    padding: 8px 0;
  }

  .preview-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    background: linear-gradient(135deg, #F0F9EB 0%, #ECF5FF 100%);
    border-radius: 8px;
    border: 1px dashed #67C23A;
  }

  .preview-icon {
    width: 48px;
    height: 48px;
    border-radius: 8px;
    background: #67C23A;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;

    i {
      font-size: 24px;
    }
  }

  .preview-text {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .preview-title {
    font-size: 14px;
    font-weight: 500;
    color: #303133;
  }

  .preview-desc {
    font-size: 12px;
    color: #606266;
  }

  .preview-tags {
    margin-top: 8px;

    .ml-2 {
      margin-left: 8px;
    }
  }
}
</style>

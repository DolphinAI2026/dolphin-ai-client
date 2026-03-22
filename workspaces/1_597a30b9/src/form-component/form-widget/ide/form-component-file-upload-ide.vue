<template>
  <div class="form-widget form-component-avatar-upload-ide">
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
      <div class="ide-avatar-preview">
        <div class="ide-avatar-circle">
          <i class="el-icon-user-solid ide-icon"></i>
        </div>
        <span class="ide-label">头像上传</span>
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
.form-component-avatar-upload-ide {
  .ide-avatar-preview {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .ide-avatar-circle {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    border: 2px dashed #dcdfe6;
    background: #f5f7fa;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .ide-icon {
    font-size: 24px;
    color: #c0c4cc;
  }

  .ide-label {
    font-size: 12px;
    color: #909399;
  }
}
</style>

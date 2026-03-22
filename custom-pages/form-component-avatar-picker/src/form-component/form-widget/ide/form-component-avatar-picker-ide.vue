<template>
  <div class="form-widget form-component-avatar-picker-ide">
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
      <div class="avatar-picker-ide-preview">
        <div class="avatar-picker-ide-avatars">
          <div class="avatar-picker-ide-item" v-for="i in 3" :key="i">
            <div class="avatar-picker-ide-circle">
              <svg viewBox="0 0 24 24" width="20" height="20">
                <circle cx="12" cy="8" r="4" fill="#C0C4CC"/>
                <path d="M4 20c0-4.4 3.6-8 8-8s8 3.6 8 8" fill="#C0C4CC"/>
              </svg>
            </div>
          </div>
          <div class="avatar-picker-ide-add">
            <i class="el-icon-plus"></i>
          </div>
        </div>
        <div class="avatar-picker-ide-desc">
          <p>人员头像选择组件（设计态预览）</p>
        </div>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentAvatarPickerIde',
  mixins: [FormWidgetMixin]
}
</script>

<style lang="scss">
.form-component-avatar-picker-ide {
  .avatar-picker-ide-preview {
    border-radius: 4px;
    border: 1px dashed #dcdfe6;
    padding: 12px;
    background: #fafafa;
  }

  .avatar-picker-ide-avatars {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }

  .avatar-picker-ide-item {
    .avatar-picker-ide-circle {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: #f0f2f5;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 1px solid #e4e7ed;
    }
  }

  .avatar-picker-ide-add {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 1px dashed #c0c4cc;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #c0c4cc;
    cursor: pointer;
    font-size: 14px;
  }

  .avatar-picker-ide-desc {
    font-size: 12px;
    color: #909399;
    line-height: 1.4;
  }
}
</style>

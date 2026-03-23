<template>
  <div class="form-widget form-component-avatar-upload-read">
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
      <div class="avatar-read-wrapper">
        <div
          v-if="formValue"
          class="avatar-read-img"
          :style="avatarStyle"
        >
          <img :src="formValue" class="inner-img" />
        </div>
        <span v-else class="avatar-empty">-</span>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentFileUploadRead',
  mixins: [FormWidgetMixin],
  computed: {
    avatarStyle() {
      const size = this.widget.customComponentConfig?.avatarSize || 60
      return {
        width: size + 'px',
        height: size + 'px',
        borderRadius: '50%'
      }
    }
  }
}
</script>

<style lang="scss">
.form-component-avatar-upload-read {
  .avatar-read-wrapper {
    display: flex;
    align-items: center;
  }

  .avatar-read-img {
    overflow: hidden;
    border: 1px solid #ebeef5;
    background: #f5f7fa;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;

    .inner-img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
  }

  .avatar-empty {
    color: #909399;
  }
}
</style>

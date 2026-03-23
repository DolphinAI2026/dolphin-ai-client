<template>
  <div class="form-widget form-component-avatar-upload-print">
    <div
      v-if="formValue"
      class="print-avatar"
      :style="avatarStyle"
    >
      <img :src="formValue" class="print-avatar-img" />
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
    avatarStyle() {
      const size = this.widget?.customComponentConfig?.avatarSize || 60
      return {
        width: size + 'px',
        height: size + 'px',
        borderRadius: '50%',
        overflow: 'hidden'
      }
    }
  }
}
</script>

<style lang="scss">
.form-component-avatar-upload-print {
  .print-avatar {
    border: 1px solid #ebeef5;
    background: #f5f7fa;
    display: inline-block;

    .print-avatar-img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
  }
}
</style>

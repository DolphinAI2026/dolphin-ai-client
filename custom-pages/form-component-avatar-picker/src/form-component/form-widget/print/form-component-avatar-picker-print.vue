<template>
  <div class="form-widget form-component-avatar-picker-print">
    <div class="avatar-picker-print-body" v-if="users.length > 0">
      <span
        v-for="(user, index) in users"
        :key="user.userId || index"
      >{{ user.userName || '-' }}<span v-if="index < users.length - 1">、</span></span>
    </div>
    <span v-else class="avatar-picker-print-empty">-</span>
  </div>
</template>

<script>
import PrintWidgetMixin from '@/mixin/print-widget.mixin'

export default {
  name: 'FormComponentAvatarPickerPrint',
  mixins: [PrintWidgetMixin],
  computed: {
    users() {
      if (!this.formValue) return []
      if (typeof this.formValue === 'string') {
        try { return JSON.parse(this.formValue) || [] } catch (e) { return [] }
      }
      if (Array.isArray(this.formValue)) return this.formValue
      return []
    }
  }
}
</script>

<style lang="scss">
.form-component-avatar-picker-print {
  .avatar-picker-print-body {
    font-size: 12px;
    color: #303133;
  }

  .avatar-picker-print-empty {
    font-size: 12px;
    color: #909399;
  }
}
</style>

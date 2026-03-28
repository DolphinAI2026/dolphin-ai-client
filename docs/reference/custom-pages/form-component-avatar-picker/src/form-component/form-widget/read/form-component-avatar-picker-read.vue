<template>
  <div class="form-widget form-component-avatar-picker-read">
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
      <div class="avatar-picker-read-body" v-if="selectedUsers.length > 0">
        <div
          class="avatar-picker-read-item"
          v-for="(user, index) in displayUsers"
          :key="user.userId || index"
          :title="user.userName || ''"
        >
          <div
            class="avatar-picker-read-avatar"
            :class="avatarShapeClass"
            :style="avatarSizeStyle"
          >
            <img
              v-if="user.avatar"
              :src="user.avatar"
              :alt="user.userName"
              class="avatar-picker-read-img"
            />
            <span v-else class="avatar-picker-read-initial" :style="initialFontStyle">
              {{ getInitial(user.userName) }}
            </span>
          </div>
          <span v-if="config.showName !== false" class="avatar-picker-read-name">
            {{ user.userName || '-' }}
          </span>
        </div>
        <div v-if="overflowCount > 0" class="avatar-picker-read-overflow">
          <div
            class="avatar-picker-read-avatar avatar-picker-read-overflow-badge"
            :class="avatarShapeClass"
            :style="avatarSizeStyle"
          >
            +{{ overflowCount }}
          </div>
        </div>
      </div>
      <div v-else class="avatar-picker-read-empty">
        <span>-</span>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentAvatarPickerRead',
  mixins: [FormWidgetMixin],
  computed: {
    config() {
      return (this.widget && this.widget.customComponentConfig) || {}
    },
    selectedUsers() {
      if (!this.formValue) return []
      if (typeof this.formValue === 'string') {
        try { return JSON.parse(this.formValue) || [] } catch (e) { return [] }
      }
      if (Array.isArray(this.formValue)) return this.formValue
      return []
    },
    maxDisplay() {
      return this.config.maxDisplay || 5
    },
    displayUsers() {
      return this.selectedUsers.slice(0, this.maxDisplay)
    },
    overflowCount() {
      return Math.max(0, this.selectedUsers.length - this.maxDisplay)
    },
    avatarShapeClass() {
      return this.config.avatarShape === 'square' ? 'is-square' : 'is-circle'
    },
    avatarSizeStyle() {
      const size = this.config.avatarSize || 36
      return {
        width: size + 'px',
        height: size + 'px',
        lineHeight: size + 'px',
        fontSize: Math.max(12, Math.floor(size * 0.4)) + 'px'
      }
    },
    initialFontStyle() {
      const size = this.config.avatarSize || 36
      return { fontSize: Math.max(12, Math.floor(size * 0.4)) + 'px' }
    }
  },
  methods: {
    getInitial(name) {
      return name ? name.charAt(0) : '?'
    }
  }
}
</script>

<style lang="scss">
.form-component-avatar-picker-read {
  .avatar-picker-read-body {
    display: flex;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 8px;
  }

  .avatar-picker-read-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }

  .avatar-picker-read-avatar {
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #e6f0ff;
    border: 1px solid #d9e6ff;
    color: #409EFF;
    font-weight: 500;

    &.is-circle { border-radius: 50%; }
    &.is-square { border-radius: 4px; }
  }

  .avatar-picker-read-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .avatar-picker-read-name {
    font-size: 12px;
    color: #606266;
    max-width: 60px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: center;
  }

  .avatar-picker-read-overflow-badge {
    background: #f0f2f5 !important;
    color: #909399 !important;
    border-color: #e4e7ed !important;
    font-size: 12px !important;
  }

  .avatar-picker-read-empty {
    color: #909399;
    font-size: 14px;
  }
}
</style>

<template>
  <div class="form-widget form-component-avatar-picker-list">
    <div class="avatar-picker-list-body" v-if="users.length > 0">
      <div
        class="avatar-picker-list-item"
        v-for="(user, index) in users.slice(0, 3)"
        :key="user.userId || index"
        :title="user.userName || ''"
      >
        <div class="avatar-picker-list-circle">
          <img
            v-if="user.avatar"
            :src="user.avatar"
            :alt="user.userName"
          />
          <span v-else class="avatar-picker-list-initial">
            {{ getInitial(user.userName) }}
          </span>
        </div>
      </div>
      <span v-if="users.length > 3" class="avatar-picker-list-more">
        +{{ users.length - 3 }}
      </span>
    </div>
    <span v-else class="avatar-picker-list-empty">-</span>
  </div>
</template>

<script>
export default {
  name: 'FormComponentAvatarPickerList',
  props: {
    componentConfig: {
      type: Object,
      default() { return {} }
    },
    formValue: {
      type: [String, Object, Array],
      default: ''
    },
    propKey: {
      type: String,
      default: ''
    }
  },
  computed: {
    users() {
      if (!this.formValue) return []
      if (typeof this.formValue === 'string') {
        try { return JSON.parse(this.formValue) || [] } catch (e) { return [] }
      }
      if (Array.isArray(this.formValue)) return this.formValue
      return []
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
.form-component-avatar-picker-list {
  .avatar-picker-list-body {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .avatar-picker-list-item {
    .avatar-picker-list-circle {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #e6f0ff;
      border: 1px solid #d9e6ff;

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
    }
  }

  .avatar-picker-list-initial {
    color: #409EFF;
    font-size: 11px;
    font-weight: 500;
  }

  .avatar-picker-list-more {
    font-size: 12px;
    color: #909399;
  }

  .avatar-picker-list-empty {
    color: #909399;
    font-size: 12px;
  }
}
</style>

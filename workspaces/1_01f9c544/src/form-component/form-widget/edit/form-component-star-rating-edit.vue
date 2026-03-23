<template>
  <div class="form-widget form-component-star-rating-edit">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div class="star-rating-wrapper" :style="wrapperStyle">
        <div
          class="star-rating-container"
          :style="containerStyle"
          @mouseleave="handleMouseLeave"
        >
          <div
            v-for="i in config.maxStars"
            :key="i"
            class="star-item"
            :style="starItemStyle"
            @mousemove="handleMouseMove($event, i)"
            @click="handleClick($event, i)"
          >
            <!-- 底层：未选中星 -->
            <svg
              class="star-icon star-inactive"
              viewBox="0 0 24 24"
              :style="{ fill: config.inactiveColor }"
            >
              <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
            </svg>
            <!-- 顶层：选中星（半星用clip-path裁切） -->
            <svg
              class="star-icon star-active"
              viewBox="0 0 24 24"
              :style="getActiveStarStyle(i)"
            >
              <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
            </svg>
          </div>
        </div>
        <!-- 评语文字 -->
        <span v-if="config.showText && currentText" class="rating-text" :style="{ color: config.activeColor }">
          {{ currentText }}
        </span>
        <!-- 清除按钮 -->
        <span v-if="formValue" class="clear-btn" @click="handleClear">
          <i class="el-icon-close" style="font-size: 12px;"></i>
        </span>
      </div>
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentStarRatingEdit',
  mixins: [FormWidgetMixin],
  data() {
    return {
      hoverValue: null
    }
  },
  computed: {
    config() {
      return this.widget.customComponentConfig || {}
    },
    starSize() {
      const sizeMap = { small: 20, medium: 28, large: 36 }
      return sizeMap[this.config.size] || 28
    },
    wrapperStyle() {
      return { display: 'inline-flex', 'align-items': 'center', gap: '8px' }
    },
    containerStyle() {
      return {
        display: 'flex',
        'align-items': 'center',
        gap: '2px',
        cursor: 'pointer'
      }
    },
    starItemStyle() {
      return {
        position: 'relative',
        width: this.starSize + 'px',
        height: this.starSize + 'px',
        'flex-shrink': '0'
      }
    },
    // 当前显示值（hover时临时显示hover预览）
    displayValue() {
      return this.hoverValue !== null ? this.hoverValue : (this.formValue || 0)
    },
    currentText() {
      const val = this.displayValue
      const texts = this.config.texts || []
      if (!texts.length || !val) return ''
      const index = Math.round(val * 2) - 1
      return texts[index] || ''
    }
  },
  methods: {
    getActiveStarStyle(starIndex) {
      const val = this.displayValue
      const fillPercent = Math.max(0, Math.min(1, val - (starIndex - 1))) * 100
      const fill = this.config.activeColor || '#FF9900'
      if (fillPercent >= 100) {
        return { fill, clipPath: 'none', position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }
      } else if (fillPercent > 0) {
        return {
          fill,
          clipPath: `inset(0 ${100 - fillPercent}% 0 0)`,
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%'
        }
      }
      return { fill, clipPath: 'inset(0 100% 0 0)', position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }
    },
    handleMouseMove(event, starIndex) {
      if (!this.config.allowHalf) {
        this.hoverValue = starIndex
        return
      }
      const rect = event.currentTarget.getBoundingClientRect()
      const x = event.clientX - rect.left
      const half = x < rect.width / 2
      this.hoverValue = half ? starIndex - 0.5 : starIndex
    },
    handleClick(event, starIndex) {
      if (!this.config.allowHalf) {
        this.formValue = starIndex
        this.hoverValue = null
        return
      }
      const rect = event.currentTarget.getBoundingClientRect()
      const x = event.clientX - rect.left
      const half = x < rect.width / 2
      this.formValue = half ? starIndex - 0.5 : starIndex
      this.hoverValue = null
    },
    handleMouseLeave() {
      this.hoverValue = null
    },
    handleClear() {
      this.formValue = null
      this.hoverValue = null
    }
  }
}
</script>
<style lang="scss">
.star-rating-wrapper {
  .star-rating-container {
    user-select: none;
  }
  .star-item {
    line-height: 0;
    overflow: hidden;
  }
  .star-icon {
    width: 100%;
    height: 100%;
    display: block;
  }
  .rating-text {
    font-size: 13px;
    margin-left: 4px;
    white-space: nowrap;
  }
  .clear-btn {
    cursor: pointer;
    color: #909399;
    display: flex;
    align-items: center;
    padding: 2px;
    border-radius: 50%;
    transition: color 0.2s;
    &:hover {
      color: #606266;
    }
  }
}
</style>

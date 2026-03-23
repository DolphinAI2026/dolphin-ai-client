<template>
  <div class="form-widget form-component-star-rating-read">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div class="star-rating-read-wrapper">
        <div class="star-rating-read-stars" :style="containerStyle">
          <span
            v-for="i in config.maxStars"
            :key="i"
            class="star-read-item"
            :style="getStarReadStyle(i)"
          >
            <svg class="star-icon" viewBox="0 0 24 24">
              <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
            </svg>
          </span>
        </div>
        <span v-if="config.showText && currentText" class="rating-read-text" :style="{ color: config.activeColor }">
          {{ currentText }}
        </span>
        <span v-else-if="!formValue" class="rating-placeholder">-</span>
      </div>
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentStarRatingRead',
  mixins: [FormWidgetMixin],
  computed: {
    config() {
      return this.widget.customComponentConfig || {}
    },
    starSize() {
      const sizeMap = { small: 16, medium: 20, large: 24 }
      return sizeMap[this.config.size] || 20
    },
    containerStyle() {
      return {
        display: 'inline-flex',
        'align-items': 'center',
        gap: '1px'
      }
    },
    currentText() {
      const val = this.formValue || 0
      const texts = this.config.texts || []
      if (!texts.length || !val) return ''
      const index = Math.min(Math.round(val * 2) - 1, texts.length - 1)
      return texts[index >= 0 ? index : 0] || ''
    }
  },
  methods: {
    getStarReadStyle(starIndex) {
      const val = this.formValue || 0
      const isActive = val >= starIndex
      const isHalf = !isActive && val >= starIndex - 0.5
      const clipPath = isHalf ? 'inset(0 50% 0 0)' : isActive ? 'none' : 'inset(0 100% 0 0)'
      return {
        display: 'inline-block',
        width: this.starSize + 'px',
        height: this.starSize + 'px',
        position: 'relative',
        clipPath,
        color: isActive ? (this.config.activeColor || '#FF9900') : (this.config.inactiveColor || '#E0E0E0'),
        fill: isActive ? (this.config.activeColor || '#FF9900') : (this.config.inactiveColor || '#E0E0E0')
      }
    }
  }
}
</script>
<style lang="scss">
.star-rating-read-wrapper {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  .star-rating-read-stars {
    display: inline-flex;
    align-items: center;
    gap: 1px;
  }
  .star-read-item {
    line-height: 0;
    overflow: hidden;
    .star-icon {
      width: 100%;
      height: 100%;
      display: block;
    }
  }
  .rating-read-text {
    font-size: 13px;
    margin-left: 2px;
  }
  .rating-placeholder {
    color: #909399;
    font-size: 13px;
  }
}
</style>

<template>
  <div class="form-widget form-component-star-rating-print">
    <div class="star-rating-print-wrapper">
      <span
        v-for="i in config.maxStars"
        :key="i"
        class="star-print-item"
        :style="getStarPrintStyle(i)"
      >
        <svg class="star-icon" viewBox="0 0 24 24">
          <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
        </svg>
      </span>
      <span v-if="config.showText && currentText" class="rating-print-text">
        {{ currentText }}
      </span>
    </div>
  </div>
</template>
<script>
import PrintWidgetMixin from '@/mixin/print-widget.mixin'

export default {
  name: 'FormComponentStarRatingPrint',
  mixins: [PrintWidgetMixin],
  computed: {
    config() {
      return this.widget.customComponentConfig || {}
    },
    starSize() {
      return 16
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
    getStarPrintStyle(starIndex) {
      const val = this.formValue || 0
      const isActive = val >= starIndex
      const isHalf = !isActive && val >= starIndex - 0.5
      const color = isActive ? (this.config.activeColor || '#FF9900') : (this.config.inactiveColor || '#E0E0E0')
      const clipPath = isHalf ? 'inset(0 50% 0 0)' : isActive ? 'none' : 'inset(0 100% 0 0)'
      return {
        display: 'inline-block',
        width: this.starSize + 'px',
        height: this.starSize + 'px',
        position: 'relative',
        color,
        fill: color,
        clipPath
      }
    }
  }
}
</script>
<style lang="scss">
.star-rating-print-wrapper {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  .star-print-item {
    line-height: 0;
    overflow: hidden;
    .star-icon {
      width: 100%;
      height: 100%;
      display: block;
    }
  }
  .rating-print-text {
    font-size: 13px;
    margin-left: 4px;
    color: #303133;
  }
}
</style>

<template>
  <div class="form-widget form-component-star-rating-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div class="star-rating-ide-wrapper">
        <div class="star-rating-ide-stars" :style="containerStyle">
          <span
            v-for="i in config.maxStars"
            :key="i"
            class="star-ide-item"
            :style="getStarIdeStyle(i)"
          >
            <svg class="star-icon" viewBox="0 0 24 24">
              <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
            </svg>
          </span>
        </div>
        <span v-if="config.showText && currentText" class="rating-ide-text" :style="{ color: config.activeColor }">
          {{ currentText }}
        </span>
      </div>
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentStarRatingIde',
  mixins: [FormWidgetMixin],
  computed: {
    config() {
      return this.widget.customComponentConfig || {}
    },
    starSize() {
      const sizeMap = { small: 20, medium: 28, large: 36 }
      return sizeMap[this.config.size] || 28
    },
    containerStyle() {
      return {
        display: 'inline-flex',
        'align-items': 'center',
        gap: '2px'
      }
    },
    previewValue() {
      return Math.max(1, Math.ceil((this.config.maxStars || 5) / 2))
    },
    currentText() {
      const texts = this.config.texts || []
      if (!texts.length) return ''
      const index = Math.min(Math.round(this.previewValue * 2) - 1, texts.length - 1)
      return texts[index >= 0 ? index : 0] || ''
    }
  },
  methods: {
    getStarIdeStyle(starIndex) {
      const val = this.previewValue
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
        clipPath,
        opacity: isActive || isHalf ? 1 : 0.4
      }
    }
  }
}
</script>
<style lang="scss">
.star-rating-ide-wrapper {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  .star-rating-ide-stars {
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
  .star-ide-item {
    line-height: 0;
    overflow: hidden;
    .star-icon {
      width: 100%;
      height: 100%;
      display: block;
    }
  }
  .rating-ide-text {
    font-size: 13px;
    margin-left: 2px;
  }
}
</style>

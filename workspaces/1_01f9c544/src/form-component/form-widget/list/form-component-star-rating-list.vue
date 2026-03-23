<template>
  <div class="form-widget form-component-star-rating-list">
    <div class="star-rating-list-wrapper">
      <div class="star-rating-list-stars" :style="containerStyle">
        <span
          v-for="i in config.maxStars"
          :key="i"
          class="star-list-item"
          :style="getStarListStyle(i)"
        >
          <svg class="star-icon" viewBox="0 0 24 24">
            <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
          </svg>
        </span>
      </div>
    </div>
  </div>
</template>
<script>
export default {
  name: 'FormComponentStarRatingList',
  props: {
    componentConfig: { type: Object, default() { return {} } },
    formValue: { type: [String, Number], default: '' },
    propKey: { type: String, default: '' }
  },
  computed: {
    config() {
      return this.componentConfig.customComponentConfig || {}
    },
    starSize() {
      const sizeMap = { small: 14, medium: 16, large: 20 }
      return sizeMap[this.config.size] || 16
    },
    containerStyle() {
      return {
        display: 'inline-flex',
        'align-items': 'center',
        gap: '1px'
      }
    }
  },
  methods: {
    getStarListStyle(starIndex) {
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
.star-rating-list-wrapper {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  .star-rating-list-stars {
    display: inline-flex;
    align-items: center;
    gap: 1px;
  }
  .star-list-item {
    line-height: 0;
    overflow: hidden;
    .star-icon {
      width: 100%;
      height: 100%;
      display: block;
    }
  }
}
</style>

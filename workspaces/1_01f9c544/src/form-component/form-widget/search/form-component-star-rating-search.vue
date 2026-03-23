<template>
  <div class="form-widget form-component-star-rating-search">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <div class="star-rating-search-wrapper">
        <el-input-number
          v-model="searchValue"
          :min="0"
          :max="config.maxStars || 5"
          :step="config.allowHalf ? 0.5 : 1"
          :precision="config.allowHalf ? 1 : 0"
          controls-position="right"
          size="mini"
          style="width: 100%;"
          placeholder="请输入评分"
          @change="handleChange"
        />
      </div>
    </x-proxy-form-item>
  </div>
</template>
<script>
import SearchWidgetMixin from '@/mixin/search-widget.mixin'

export default {
  name: 'FormComponentStarRatingSearch',
  mixins: [SearchWidgetMixin],
  computed: {
    config() {
      return this.widget.customComponentConfig || {}
    },
    searchValue: {
      get() {
        return this.formValue
      },
      set(val) {
        this.formValue = val
      }
    }
  },
  methods: {
    handleChange(val) {
      this.$formEventEmit('change', val)
    }
  }
}
</script>
<style lang="scss">
.star-rating-search-wrapper {
  width: 100%;
}
</style>

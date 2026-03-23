<template>
  <div class="form-widget form-component-material-verify-read">
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
      <div class="read-container" v-if="hasData">
        <!-- 照片预览 -->
        <div class="photo-preview" v-if="photoList.length > 0">
          <div class="photo-thumb-list">
            <el-image
              v-for="(photo, index) in photoList.slice(0, 4)"
              :key="index"
              :src="photo.url"
              fit="cover"
              class="photo-thumb"
              :preview-src-list="photoList.map(p => p.url)"
            />
            <div v-if="photoList.length > 4" class="photo-more">
              +{{ photoList.length - 4 }}
            </div>
          </div>
          <span class="photo-info">{{ photoList.length }}张照片</span>
        </div>

        <!-- 识别结果 -->
        <div v-if="recognizedMaterials.length > 0" class="recognized-info">
          <el-tag size="mini" type="success" class="ml-2">
            <i class="el-icon-microphone"></i>
            已识别 {{ recognizedMaterials.length }} 种物料
          </el-tag>
        </div>

        <!-- 比对结果 -->
        <div v-if="compareSummary" class="compare-result">
          <el-tag
            :type="compareSummary.pass ? 'success' : 'warning'"
            size="small"
          >
            <i :class="compareSummary.pass ? 'el-icon-success' : 'el-icon-warning'"></i>
            {{ compareSummary.pass ? '验收通过' : '需核查' }}
          </el-tag>
        </div>
      </div>
      <span v-else class="no-data">-</span>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentFileUploadRead',
  mixins: [FormWidgetMixin],
  computed: {
    // 解析保存的值
    savedValue() {
      return this.formValue || {}
    },
    photoList() {
      return this.savedValue.photos || []
    },
    recognizedMaterials() {
      return this.savedValue.recognized || []
    },
    compareSummary() {
      return this.savedValue.compareResult || null
    },
    hasData() {
      return this.photoList.length > 0 || this.recognizedMaterials.length > 0
    }
  }
}
</script>

<style lang="scss">
.form-component-material-verify-read {
  .read-container {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .photo-preview {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .photo-thumb-list {
    display: flex;
    gap: 4px;
  }

  .photo-thumb {
    width: 36px;
    height: 36px;
    border-radius: 4px;
    cursor: pointer;
    border: 1px solid #EBEEF5;
  }

  .photo-more {
    width: 36px;
    height: 36px;
    border-radius: 4px;
    background: #F5F7FA;
    color: #909399;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    cursor: pointer;
  }

  .photo-info {
    font-size: 12px;
    color: #909399;
  }

  .recognized-info {
    .ml-2 {
      margin-left: 8px;
    }
  }

  .compare-result {
    margin-left: auto;
  }

  .no-data {
    color: #C0C4CC;
  }
}
</style>

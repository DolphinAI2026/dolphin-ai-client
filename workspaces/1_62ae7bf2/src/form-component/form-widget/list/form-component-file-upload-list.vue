<template>
  <div class="form-widget form-component-material-verify-list">
    <div v-if="hasData" class="list-preview">
      <!-- 照片缩略图 -->
      <div class="list-photos">
        <el-image
          v-for="(photo, index) in photoList.slice(0, 3)"
          :key="index"
          :src="photo.url"
          fit="cover"
          class="list-thumb"
          :preview-src-list="photoList.map(p => p.url)"
        />
        <span v-if="photoList.length > 3" class="more-count">+{{ photoList.length - 3 }}</span>
      </div>

      <!-- 识别物料数 -->
      <el-tag v-if="materialCount > 0" size="mini" type="success" class="ml-2">
        {{ materialCount }}种物料
      </el-tag>

      <!-- 验收状态 -->
      <el-tag
        v-if="compareSummary"
        :type="compareSummary.pass ? 'success' : 'warning'"
        size="mini"
        class="ml-2"
      >
        {{ compareSummary.pass ? '通过' : '需核查' }}
      </el-tag>
    </div>
    <span v-else class="no-data">-</span>
  </div>
</template>

<script>
export default {
  name: 'FormComponentFileUploadList',
  props: {
    componentConfig: { type: Object, default() { return {} } },
    formValue: { type: [String, Object, Array], default: '' },
    propKey: { type: String, default: '' }
  },
  computed: {
    savedValue() {
      return typeof this.formValue === 'object' ? this.formValue : {}
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
    materialCount() {
      return this.recognizedMaterials.length
    },
    hasData() {
      return this.photoList.length > 0 || this.materialCount > 0
    }
  }
}
</script>

<style lang="scss">
.form-component-material-verify-list {
  .list-preview {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .list-photos {
    display: flex;
    align-items: center;
    gap: 2px;
  }

  .list-thumb {
    width: 24px;
    height: 24px;
    border-radius: 3px;
    cursor: pointer;
    border: 1px solid #EBEEF5;
  }

  .more-count {
    font-size: 11px;
    color: #909399;
    margin-left: 2px;
  }

  .ml-2 {
    margin-left: 4px;
  }

  .no-data {
    color: #C0C4CC;
  }
}
</style>

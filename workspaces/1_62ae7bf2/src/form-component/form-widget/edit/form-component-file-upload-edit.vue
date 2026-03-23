<template>
  <div class="form-widget form-component-material-verify-edit">
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
      <div class="material-verify-container">
        <!-- 图片上传区域 -->
        <div class="upload-section">
          <div class="section-header">
            <span class="section-title">现场物料照片</span>
            <span class="photo-count">{{ photoList.length }}/{{ maxPhotoCount }}张</span>
          </div>
          <div class="upload-area" :class="{ 'is-drag': isDragging }" @dragover.prevent="isDragging = true" @dragleave="isDragging = false" @drop.prevent="handleDrop">
            <div v-if="photoList.length === 0" class="upload-placeholder" @click="triggerUpload">
              <i class="el-icon-upload2"></i>
              <p>点击或拖拽上传照片</p>
              <p class="upload-tip">支持 JPG、PNG 格式</p>
            </div>
            <div v-else class="photo-grid">
              <div v-for="(photo, index) in photoList" :key="index" class="photo-item">
                <el-image :src="photo.url" fit="cover" :preview-src-list="photoList.map(p => p.url)">
                  <div slot="placeholder" class="image-placeholder">
                    <i class="el-icon-loading"></i>
                  </div>
                </el-image>
                <div class="photo-actions">
                  <span v-if="photo.recognized" class="ai-tag">
                    <i class="el-icon-circle-check"></i> 已识别
                  </span>
                  <span v-if="photo.matched" class="match-tag success">
                    <i class="el-icon-success"></i> 匹配
                  </span>
                  <span v-else-if="photo.matched === false" class="match-tag warning">
                    <i class="el-icon-warning"></i> 不匹配
                  </span>
                </div>
                <i class="el-icon-close photo-delete" @click="removePhoto(index)"></i>
              </div>
              <div v-if="photoList.length < maxPhotoCount" class="photo-add" @click="triggerUpload">
                <i class="el-icon-plus"></i>
                <span>添加照片</span>
              </div>
            </div>
          </div>
          <input ref="fileInput" type="file" accept="image/*" multiple style="display: none" @change="handleFileSelect" />
        </div>

        <!-- AI识别按钮 -->
        <div class="action-bar" v-if="photoList.length > 0">
          <el-button type="primary" size="small" :loading="recognizing" @click="startRecognition">
            <i class="el-icon-microphone"></i>
            {{ recognizing ? '识别中...' : 'AI识别物料' }}
          </el-button>
          <el-button v-if="recognizedMaterials.length > 0" type="success" size="small" :loading="comparing" @click="compareWithQuote">
            <i class="el-icon-document"></i>
            {{ comparing ? '比对中...' : '与报价单比对' }}
          </el-button>
          <el-button size="small" @click="clearAll">
            <i class="el-icon-delete"></i>
            清空
          </el-button>
        </div>

        <!-- 识别结果区域 -->
        <div v-if="recognizedMaterials.length > 0" class="result-section">
          <div class="section-header">
            <span class="section-title">AI识别结果</span>
            <el-tag size="mini" type="info">共识别 {{ recognizedMaterials.length }} 种物料</el-tag>
          </div>
          <el-table :data="recognizedMaterials" border size="small" class="result-table">
            <el-table-column prop="name" label="物料名称" min-width="120" />
            <el-table-column prop="count" label="识别数量" width="100" align="center" />
            <el-table-column prop="confidence" label="置信度" width="100">
              <template slot-scope="{ row }">
                <el-progress :percentage="Math.round(row.confidence * 100)" :color="getProgressColor(row.confidence)" />
              </template>
            </el-table-column>
            <el-table-column label="报价单数量" width="110" align="center">
              <template slot-scope="{ row }">
                <span v-if="row.quoteCount !== undefined">{{ row.quoteCount }}</span>
                <span v-else class="no-data">-</span>
              </template>
            </el-table-column>
            <el-table-column label="比对结果" width="100" align="center">
              <template slot-scope="{ row }">
                <el-tag v-if="row.matchStatus === 'match'" type="success" size="mini">匹配</el-tag>
                <el-tag v-else-if="row.matchStatus === 'over'" type="warning" size="mini">超出</el-tag>
                <el-tag v-else-if="row.matchStatus === 'lack'" type="danger" size="mini">不足</el-tag>
                <span v-else class="no-data">-</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 比对汇总 -->
        <div v-if="compareSummary" class="summary-section">
          <el-alert
            :title="compareSummary.title"
            :type="compareSummary.type"
            :description="compareSummary.description"
            show-icon
            :closable="false"
          >
            <template>
              <div class="summary-content">
                <div class="summary-item">
                  <span class="label">匹配物料：</span>
                  <span class="value success">{{ compareSummary.matchCount }} 种</span>
                </div>
                <div class="summary-item">
                  <span class="label">不匹配物料：</span>
                  <span class="value warning">{{ compareSummary.mismatchCount }} 种</span>
                </div>
                <div class="summary-item">
                  <span class="label">验证结论：</span>
                  <span class="value" :class="compareSummary.pass ? 'success' : 'danger'">
                    {{ compareSummary.pass ? '验收通过' : '需核查' }}
                  </span>
                </div>
              </div>
            </template>
          </el-alert>
        </div>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
import { QUERY_LIST_PAGE_API } from '@/api'

export default {
  name: 'FormComponentFileUploadEdit',
  mixins: [FormWidgetMixin],
  data() {
    return {
      // 照片列表
      photoList: [],
      isDragging: false,
      recognizing: false,
      comparing: false,
      // 识别的物料列表
      recognizedMaterials: [],
      // 报价单数据
      quoteData: [],
      // 比对结果
      compareSummary: null
    }
  },
  computed: {
    // 从配置获取参数
    customConfig() {
      return this.widget.customComponentConfig || {}
    },
    enableAI() {
      return this.customConfig.enableAI !== false
    },
    maxPhotoCount() {
      return this.customConfig.maxPhotoCount || 10
    },
    autoRecognize() {
      return this.customConfig.autoRecognize === true
    },
    // 获取完整数据用于比对
    editValue: {
      get() {
        return this.formValue || {
          photos: [],
          recognized: [],
          compareResult: null
        }
      },
      set(val) {
        this.formValue = val
      }
    }
  },
  created() {
    // 从已有值恢复
    const savedValue = this.formValue
    if (savedValue) {
      if (savedValue.photos) this.photoList = savedValue.photos
      if (savedValue.recognized) this.recognizedMaterials = savedValue.recognized
      if (savedValue.compareResult) this.compareSummary = savedValue.compareResult
    }
  },
  methods: {
    // 触发文件上传
    triggerUpload() {
      this.$refs.fileInput.click()
    },

    // 处理文件选择
    handleFileSelect(event) {
      const files = event.target.files
      this.processFiles(files)
      event.target.value = '' // 清空选择，允许重复选择同一文件
    },

    // 处理拖拽
    handleDrop(event) {
      this.isDragging = false
      const files = event.dataTransfer.files
      this.processFiles(files)
    },

    // 处理文件
    processFiles(files) {
      const validFiles = Array.from(files).filter(file => {
        const isImage = file.type.startsWith('image/')
        const isValidSize = file.size <= 10 * 1024 * 1024 // 10MB
        if (!isImage) {
          this.$message.warning('仅支持图片文件')
          return false
        }
        if (!isValidSize) {
          this.$message.warning('图片大小不能超过10MB')
          return false
        }
        return true
      })

      const remaining = this.maxPhotoCount - this.photoList.length
      const filesToProcess = validFiles.slice(0, remaining)

      filesToProcess.forEach(file => {
        const reader = new FileReader()
        reader.onload = (e) => {
          this.photoList.push({
            url: e.target.result,
            name: file.name,
            recognized: false,
            matched: null
          })
          // 自动识别
          if (this.autoRecognize) {
            this.startRecognition()
          }
        }
        reader.readAsDataURL(file)
      })

      if (validFiles.length > remaining) {
        this.$message.warning(`最多只能上传${this.maxPhotoCount}张照片`)
      }

      this.saveValue()
    },

    // 删除照片
    removePhoto(index) {
      this.photoList.splice(index, 1)
      this.saveValue()
    },

    // 清空所有
    clearAll() {
      this.$confirm('确定要清空所有照片和识别结果吗？', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(() => {
        this.photoList = []
        this.recognizedMaterials = []
        this.compareSummary = null
        this.saveValue()
        this.$message.success('已清空')
      }).catch(() => {})
    },

    // AI识别物料
    async startRecognition() {
      if (this.photoList.length === 0) {
        this.$message.warning('请先上传照片')
        return
      }

      this.recognizing = true

      try {
        // 模拟AI识别（实际项目中替换为真实API调用）
        // const formData = new FormData()
        // this.photoList.forEach((photo, index) => {
        //   formData.append(`photo_${index}`, photo.url)
        // })
        // const result = await this.$request({
        //   ...MATERIAL_RECOGNIZE_API,
        //   data: {
        //     photos: this.photoList.map(p => p.url),
        //     model: this.customConfig.aiModel || 'general'
        //   }
        // }).asyncThen(res => res).asyncErrorCatch(err => { throw err })

        // 模拟返回结果
        await this.$nextTick()
        await new Promise(resolve => setTimeout(resolve, 1500))

        // 模拟识别结果
        this.recognizedMaterials = [
          { name: '水泥（普通硅酸盐42.5）', count: 25, confidence: 0.95, quoteCount: undefined, matchStatus: null },
          { name: '黄沙（中粗砂）', count: 3.5, confidence: 0.88, quoteCount: undefined, matchStatus: null },
          { name: '碎石（5-20mm）', count: 4, confidence: 0.82, quoteCount: undefined, matchStatus: null }
        ]

        // 标记照片已识别
        this.photoList.forEach(photo => {
          photo.recognized = true
        })

        this.$message.success('识别完成')
      } catch (error) {
        console.error('AI识别失败:', error)
        this.$message.error('AI识别失败，请重试')
      } finally {
        this.recognizing = false
        this.saveValue()
      }
    },

    // 获取报价单数据
    async fetchQuoteData() {
      try {
        const quoteFormId = this.customConfig.quoteFormId
        const materialNameField = this.customConfig.materialNameField
        const quantityField = this.customConfig.quantityField

        if (!quoteFormId) {
          // 如果没有配置报价单表单ID，尝试从表单数据中获取
          if (materialNameField && this.globalFormData && this.globalFormData[materialNameField]) {
            // 从全局表单数据获取
            const materials = this.globalFormData[materialNameField]
            if (Array.isArray(materials)) {
              return materials.map(item => ({
                name: item[materialNameField] || item.materialName || '',
                quantity: item[quantityField] || item.quantity || 0
              })).filter(m => m.name)
            }
          }

          // 尝试从 formValue 中获取关联的报价单数据
          if (this.formValue && this.formValue.quoteData) {
            return this.formValue.quoteData
          }

          this.$message.warning('请先在组件配置中选择报价单表单')
          return []
        }

        // 调用平台API获取报价单数据
        const result = await this.$request({
          ...QUERY_LIST_PAGE_API,
          data: {
            formId: quoteFormId,
            page: 1,
            pageSize: 100
          }
        }).asyncThen(res => res).asyncErrorCatch(err => {
          console.error('API调用失败:', err)
          return null
        })

        if (result && result.data) {
          // 提取物料数据
          const quoteList = Array.isArray(result.data) ? result.data : result.data.list || []

          // 如果配置了字段映射，使用映射字段
          if (materialNameField && quantityField) {
            return quoteList.map(item => ({
              name: item[materialNameField] || item.materialName || '',
              quantity: Number(item[quantityField] || item.quantity || 0)
            })).filter(m => m.name)
          }

          // 否则尝试从数据中推断字段
          return this.inferMaterialFields(quoteList)
        }

        // 如果API调用没有返回数据，尝试其他方式
        return this.fetchQuoteDataFromAlternative(quoteFormId)
      } catch (error) {
        console.error('获取报价单数据失败:', error)
        return []
      }
    },

    // 备选方式获取报价单数据
    async fetchQuoteDataFromAlternative(quoteFormId) {
      try {
        // 尝试使用不同的API端点
        const result = await this.$request({
          url: '/xdap-app/business/v2/query/getBusinessData',
          method: 'POST',
          data: { formId: quoteFormId }
        }).asyncThen(res => res).asyncErrorCatch(() => null)

        if (result && result.data) {
          const data = Array.isArray(result.data) ? result.data : [result.data]
          return this.inferMaterialFields(data)
        }
      } catch (e) {
        console.error('备选API也失败:', e)
      }

      // 最后尝试从全局表单数据中获取
      if (this.globalFormData) {
        const materials = this.globalFormData.materials ||
                          this.globalFormData.quoteItems ||
                          this.globalFormData.itemList ||
                          []
        if (Array.isArray(materials) && materials.length > 0) {
          return materials.map(item => ({
            name: item.name || item.materialName || item.productName || '',
            quantity: Number(item.quantity || item.count || item.amount || 0)
          })).filter(m => m.name)
        }
      }

      this.$message.error('无法获取报价单数据，请检查配置')
      return []
    },

    // 从数据中推断物料字段
    inferMaterialFields(dataList) {
      if (!dataList || dataList.length === 0) return []

      // 常见的物料名称字段
      const nameFields = ['materialName', 'material_name', 'name', 'productName', 'product_name', 'itemName', 'item_name', 'goodsName', 'spec']
      // 常见的数量字段
      const quantityFields = ['quantity', 'qty', 'count', 'amount', 'num', 'number', 'total', 'sum']

      // 从第一条数据中找到对应字段
      const firstItem = dataList[0]
      let nameField = ''
      let quantityField = ''

      for (const field of nameFields) {
        if (firstItem[field]) {
          nameField = field
          break
        }
      }

      for (const field of quantityFields) {
        if (firstItem[field] !== undefined) {
          quantityField = field
          break
        }
      }

      if (!nameField) {
        // 如果找不到标准字段，返回所有文本字段作为备选
        const textFields = Object.keys(firstItem).filter(k =>
          typeof firstItem[k] === 'string' && firstItem[k].length > 0 && firstItem[k].length < 100
        )
        if (textFields.length > 0) {
          return dataList.map(item => ({
            name: item[textFields[0]] || '',
            quantity: 0
          })).filter(m => m.name)
        }
        return []
      }

      return dataList.map(item => ({
        name: item[nameField] || '',
        quantity: Number(item[quantityField] || 0)
      })).filter(m => m.name)
    },

    // 与报价单比对
    async compareWithQuote() {
      if (this.recognizedMaterials.length === 0) {
        this.$message.warning('请先进行AI识别')
        return
      }

      this.comparing = true

      try {
        // 获取报价单数据
        this.quoteData = await this.fetchQuoteData()

        if (this.quoteData.length === 0) {
          this.$message.info('未找到报价单数据，请检查配置')
          this.comparing = false
          return
        }

        const threshold = this.customConfig.matchThreshold || 0.8

        // 执行比对
        this.recognizedMaterials.forEach(item => {
          // 查找匹配的报价单物料（模糊匹配）
          const matchedQuote = this.quoteData.find(q =>
            this.fuzzyMatch(item.name, q.name) >= threshold
          )

          if (matchedQuote) {
            item.quoteCount = matchedQuote.quantity
            const diff = item.count - matchedQuote.quantity
            const ratio = diff / matchedQuote.quantity

            if (Math.abs(ratio) <= 0.1) {
              item.matchStatus = 'match'
            } else if (diff > 0) {
              item.matchStatus = 'over'
            } else {
              item.matchStatus = 'lack'
            }
          } else {
            item.quoteCount = undefined
            item.matchStatus = null
          }
        })

        // 生成比对汇总
        const matchCount = this.recognizedMaterials.filter(m => m.matchStatus === 'match').length
        const mismatchCount = this.recognizedMaterials.filter(m => m.matchStatus === 'over' || m.matchStatus === 'lack').length
        const unmatched = this.recognizedMaterials.filter(m => !m.matchStatus).length

        const pass = matchCount > 0 && mismatchCount === 0

        this.compareSummary = {
          title: pass ? '验收通过' : '需要核查',
          type: pass ? 'success' : 'warning',
          description: pass
            ? '现场物料与报价单基本一致，执行真实性验证通过'
            : '现场物料与报价单存在差异，请人工核查',
          matchCount: matchCount,
          mismatchCount: mismatchCount + unmatched,
          pass: pass
        }

        // 标记照片匹配状态
        this.photoList.forEach(photo => {
          if (photo.recognized) {
            photo.matched = matchCount > 0
          }
        })

        this.saveValue()
        this.$message.success('比对完成')
      } catch (error) {
        console.error('比对失败:', error)
        this.$message.error('比对失败，请重试')
      } finally {
        this.comparing = false
      }
    },

    // 模糊匹配
    fuzzyMatch(str1, str2) {
      if (!str1 || !str2) return 0
      const s1 = str1.toLowerCase()
      const s2 = str2.toLowerCase()

      if (s1 === s2) return 1

      // 包含关系
      if (s1.includes(s2) || s2.includes(s1)) {
        return 0.9
      }

      // 关键词匹配
      const keywords1 = s1.split(/[（()】【\s]/).filter(Boolean)
      const keywords2 = s2.split(/[（()】【\s]/).filter(Boolean)
      const common = keywords1.filter(k => keywords2.some(k2 => k.includes(k2) || k2.includes(k)))
      const similarity = common.length / Math.max(keywords1.length, keywords2.length)

      return similarity
    },

    // 进度条颜色
    getProgressColor(confidence) {
      if (confidence >= 0.9) return '#67C23A'
      if (confidence >= 0.7) return '#E6A23C'
      return '#F56C6C'
    },

    // 保存值
    saveValue() {
      this.formValue = {
        photos: this.photoList,
        recognized: this.recognizedMaterials,
        compareResult: this.compareSummary
      }
    }
  }
}
</script>

<style lang="scss">
.form-component-material-verify-edit {
  .material-verify-container {
    padding: 12px 0;
  }

  .upload-section {
    margin-bottom: 12px;
  }

  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;

    .section-title {
      font-size: 14px;
      font-weight: 500;
      color: #303133;
    }

    .photo-count {
      font-size: 12px;
      color: #909399;
    }
  }

  .upload-area {
    border: 1px dashed #DCDFE6;
    border-radius: 6px;
    padding: 16px;
    transition: all 0.3s;
    background: #FAFBFC;

    &.is-drag {
      border-color: #409EFF;
      background: #ECF5FF;
    }
  }

  .upload-placeholder {
    text-align: center;
    padding: 30px 0;
    cursor: pointer;
    color: #909399;

    i {
      font-size: 48px;
      margin-bottom: 8px;
    }

    p {
      margin: 4px 0;
    }

    .upload-tip {
      font-size: 12px;
      color: #C0C4CC;
    }

    &:hover {
      color: #409EFF;
    }
  }

  .photo-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
    gap: 12px;
  }

  .photo-item {
    position: relative;
    aspect-ratio: 1;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #EBEEF5;

    .el-image {
      width: 100%;
      height: 100%;
    }

    .image-placeholder {
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #F5F7FA;
      color: #C0C4CC;
    }

    .photo-actions {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      padding: 4px;
      background: rgba(0, 0, 0, 0.6);
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
    }

    .ai-tag,
    .match-tag {
      font-size: 10px;
      padding: 2px 4px;
      border-radius: 3px;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 2px;
    }

    .ai-tag {
      background: #409EFF;
    }

    .match-tag {
      &.success {
        background: #67C23A;
      }
      &.warning {
        background: #E6A23C;
      }
    }

    .photo-delete {
      position: absolute;
      top: 4px;
      right: 4px;
      width: 20px;
      height: 20px;
      background: rgba(0, 0, 0, 0.5);
      border-radius: 50%;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      opacity: 0;
      transition: opacity 0.3s;

      &:hover {
        background: #F56C6C;
      }
    }

    &:hover .photo-delete {
      opacity: 1;
    }
  }

  .photo-add {
    aspect-ratio: 1;
    border: 1px dashed #DCDFE6;
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: #909399;
    transition: all 0.3s;

    i {
      font-size: 24px;
      margin-bottom: 4px;
    }

    span {
      font-size: 12px;
    }

    &:hover {
      border-color: #409EFF;
      color: #409EFF;
    }
  }

  .action-bar {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
    padding: 8px 0;
  }

  .result-section {
    margin-bottom: 12px;
    padding: 12px;
    background: #F5F7FA;
    border-radius: 6px;

    .result-table {
      margin-top: 8px;
      background: #fff;

      .no-data {
        color: #C0C4CC;
      }
    }
  }

  .summary-section {
    .summary-content {
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
    }

    .summary-item {
      .label {
        color: #606266;
      }

      .value {
        font-weight: 500;

        &.success {
          color: #67C23A;
        }

        &.warning {
          color: #E6A23C;
        }

        &.danger {
          color: #F56C6C;
        }
      }
    }
  }
}
</style>

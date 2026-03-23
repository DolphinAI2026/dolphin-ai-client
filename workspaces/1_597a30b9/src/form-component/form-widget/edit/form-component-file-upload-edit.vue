<template>
  <div class="form-widget form-component-avatar-upload-edit">
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
      <div class="avatar-uploader-wrapper" :class="{ 'is-disabled': widget.readOnly || disabled }">
        <!-- 已有头像预览区 -->
        <div class="avatar-preview-zone" @click="triggerUpload">
          <img
            v-if="previewUrl"
            :src="previewUrl"
            class="avatar-img"
          />
          <div v-else class="avatar-placeholder">
            <i class="el-icon-plus avatar-icon"></i>
          </div>
          <!-- 悬浮操作层 -->
          <div class="avatar-hover-overlay">
            <span class="overlay-text">{{ previewUrl ? '重新上传' : '上传头像' }}</span>
          </div>
        </div>

        <!-- 上传按钮（无头像时） -->
        <div v-if="!previewUrl && !widget.readOnly && !disabled" class="upload-tip-text">
          <el-button size="mini" type="primary" plain @click="triggerUpload">选择图片</el-button>
          <span class="tip-label">支持 JPG/PNG，建议 200×200</span>
        </div>

        <!-- 删除按钮 -->
        <div v-if="previewUrl && !widget.readOnly && !disabled" class="avatar-action-btns">
          <el-button size="mini" @click="openCropDialog">裁剪</el-button>
          <el-button size="mini" type="danger" plain @click="removeAvatar">删除</el-button>
        </div>
      </div>

      <!-- 隐藏的文件上传input -->
      <input
        ref="fileInput"
        type="file"
        accept="image/jpeg,image/png,image/jpg,image/gif,image/webp"
        style="display:none"
        @change="handleFileChange"
      />

      <!-- 裁剪弹窗 -->
      <el-dialog
        title="裁剪头像"
        :visible.sync="cropDialogVisible"
        width="600px"
        :close-on-click-modal="false"
        append-to-body
      >
        <div class="crop-container">
          <div class="crop-area">
            <img
              ref="cropImage"
              :src="cropImageSrc"
              class="crop-target-image"
              @load="initCrop"
            />
          </div>
          <div class="crop-preview-wrapper">
            <p class="preview-label">预览效果</p>
            <div class="crop-preview-circle" :style="previewCircleStyle">
              <img v-if="cropPreviewUrl" :src="cropPreviewUrl" class="preview-img" />
            </div>
            <div class="scale-control">
              <span>缩放：</span>
              <el-slider
                v-model="scaleValue"
                :min="10"
                :max="200"
                :step="1"
                :show-tooltip="true"
                @input="updateCropPreview"
              ></el-slider>
              <span class="scale-value">{{ scaleValue }}%</span>
            </div>
          </div>
        </div>
        <div slot="footer" class="dialog-footer">
          <el-button @click="cropDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="confirmCrop">确定裁剪</el-button>
        </div>
      </el-dialog>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentFileUploadEdit',
  mixins: [FormWidgetMixin],
  data() {
    return {
      previewUrl: '',
      cropDialogVisible: false,
      cropImageSrc: '',
      cropImageObj: null,
      cropCanvas: null,
      cropCtx: null,
      cropPreviewUrl: '',
      scaleValue: 100,
      cropData: {
        x: 0,
        y: 0,
        width: 0,
        height: 0
      },
      // 拖拽裁剪框状态
      isDragging: false,
      dragStartX: 0,
      dragStartY: 0,
      dragType: '', // 'move' | 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'
      // 裁剪框配置
      cropBoxSize: 200,
      minCropSize: 20,
      // 当前裁剪框尺寸（跟随缩放）
      currentCropSize: 200
    }
  },
  computed: {
    disabled() {
      return false
    },
    previewCircleStyle() {
      const size = this.widget.customComponentConfig?.avatarSize || 100
      return {
        width: size + 'px',
        height: size + 'px'
      }
    },
    avatarSize() {
      return this.widget.customComponentConfig?.avatarSize || 100
    }
  },
  watch: {
    formValue: {
      immediate: true,
      handler(val) {
        if (val) {
          this.previewUrl = val
        } else {
          this.previewUrl = ''
        }
      }
    }
  },
  mounted() {
    this.initCropCanvas()
  },
  methods: {
    triggerUpload() {
      if (this.widget.readOnly || this.disabled) return
      this.$refs.fileInput.click()
    },

    handleFileChange(e) {
      const file = e.target.files[0]
      if (!file) return
      if (!file.type.startsWith('image/')) {
        this.$message.warning('请选择图片文件')
        return
      }
      const maxSize = (this.widget.customComponentConfig?.maxFileSize || 5) * 1024 * 1024
      if (file.size > maxSize) {
        this.$message.warning(`图片大小不能超过${this.widget.customComponentConfig?.maxFileSize || 5}MB`)
        return
      }
      const reader = new FileReader()
      reader.onload = (event) => {
        this.cropImageSrc = event.target.result
        this.scaleValue = 100
        this.cropDialogVisible = true
      }
      reader.readAsDataURL(file)
      e.target.value = ''
    },

    initCropCanvas() {
      this.$nextTick(() => {
        const canvas = document.createElement('canvas')
        this.cropCanvas = canvas
        this.cropCtx = canvas.getContext('2d')
      })
    },

    initCrop() {
      if (!this.$refs.cropImage) return
      const img = this.$refs.cropImage
      this.cropImageObj = img

      // 绘制裁剪画布
      const imgWidth = img.naturalWidth
      const imgHeight = img.naturalHeight

      // 裁剪框默认大小为200px或图片较小边
      const defaultSize = Math.min(200, imgWidth, imgHeight)
      this.cropBoxSize = defaultSize
      this.currentCropSize = defaultSize

      // 初始化裁剪区域（居中）
      this.cropData = {
        x: imgWidth / 2 - defaultSize / 2,
        y: imgHeight / 2 - defaultSize / 2,
        width: defaultSize,
        height: defaultSize
      }

      this.drawCropOverlay(img, imgWidth, imgHeight)
      this.updateCropPreview()
    },

    drawCropOverlay(img, imgWidth, imgHeight) {
      if (!this.cropCanvas || !this.cropCtx) return
      const canvas = this.cropCanvas
      const ctx = this.cropCtx

      // 设置canvas尺寸
      canvas.width = imgWidth
      canvas.height = imgHeight

      // 清除并绘制原图
      ctx.clearRect(0, 0, imgWidth, imgHeight)
      ctx.drawImage(img, 0, 0, imgWidth, imgHeight)

      // 绘制暗色遮罩（不包括裁剪区域）
      ctx.fillStyle = 'rgba(0, 0, 0, 0.6)'
      ctx.fillRect(0, 0, imgWidth, imgHeight)

      // 清除裁剪区域（还原原图）
      const { x, y, width, height } = this.cropData
      ctx.clearRect(x, y, width, height)
      ctx.drawImage(img, x, y, width, height, x, y, width, height)

      // 绘制裁剪边框
      ctx.strokeStyle = '#409EFF'
      ctx.lineWidth = 2
      ctx.strokeRect(x, y, width, height)

      // 绘制裁剪框上的参考线（3x3格）
      ctx.strokeStyle = 'rgba(255,255,255,0.5)'
      ctx.lineWidth = 1
      for (let i = 1; i < 3; i++) {
        // 垂直线
        ctx.beginPath()
        ctx.moveTo(x + (width / 3) * i, y)
        ctx.lineTo(x + (width / 3) * i, y + height)
        ctx.stroke()
        // 水平线
        ctx.beginPath()
        ctx.moveTo(x, y + (height / 3) * i)
        ctx.lineTo(x + width, y + (height / 3) * i)
        ctx.stroke()
      }

      // 绘制8个调整手柄
      const handleSize = 8
      ctx.fillStyle = '#fff'
      ctx.strokeStyle = '#409EFF'
      ctx.lineWidth = 2
      const handles = this.getHandlePositions(x, y, width, height)
      handles.forEach(h => {
        ctx.fillRect(h.rx - handleSize / 2, h.ry - handleSize / 2, handleSize, handleSize)
        ctx.strokeRect(h.rx - handleSize / 2, h.ry - handleSize / 2, handleSize, handleSize)
      })
    },

    getHandlePositions(x, y, w, h) {
      return [
        { type: 'nw', rx: x, ry: y },
        { type: 'n', rx: x + w / 2, ry: y },
        { type: 'ne', rx: x + w, ry: y },
        { type: 'e', rx: x + w, ry: y + h / 2 },
        { type: 'se', rx: x + w, ry: y + h },
        { type: 's', rx: x + w / 2, ry: y + h },
        { type: 'sw', rx: x, ry: y + h },
        { type: 'w', rx: x, ry: y + h / 2 }
      ]
    },

    updateCropPreview() {
      if (!this.cropImageObj || !this.cropCanvas) return
      const img = this.cropImageObj
      const { x, y, width, height } = this.cropData
      const scale = this.scaleValue / 100
      const previewSize = Math.round(this.avatarSize * scale)

      // 创建预览canvas
      const previewCanvas = document.createElement('canvas')
      previewCanvas.width = previewSize
      previewCanvas.height = previewSize
      const previewCtx = previewCanvas.getContext('2d')

      // 圆形裁剪
      previewCtx.beginPath()
      previewCtx.arc(previewSize / 2, previewSize / 2, previewSize / 2, 0, Math.PI * 2)
      previewCtx.closePath()
      previewCtx.clip()

      previewCtx.drawImage(img, x, y, width, height, 0, 0, previewSize, previewSize)
      this.cropPreviewUrl = previewCanvas.toDataURL('image/jpeg', 0.9)
    },

    confirmCrop() {
      if (!this.cropImageObj) return
      const img = this.cropImageObj
      const { x, y, width, height } = this.cropData
      const outputSize = this.avatarSize

      const outputCanvas = document.createElement('canvas')
      outputCanvas.width = outputSize
      outputCanvas.height = outputSize
      const outputCtx = outputCanvas.getContext('2d')

      // 圆形裁剪
      outputCtx.beginPath()
      outputCtx.arc(outputSize / 2, outputSize / 2, outputSize / 2, 0, Math.PI * 2)
      outputCtx.closePath()
      outputCtx.clip()

      outputCtx.drawImage(img, x, y, width, height, 0, 0, outputSize, outputSize)
      const resultUrl = outputCanvas.toDataURL('image/jpeg', 0.92)
      this.previewUrl = resultUrl
      this.formValue = resultUrl
      this.cropDialogVisible = false
    },

    removeAvatar() {
      this.previewUrl = ''
      this.formValue = ''
      this.cropPreviewUrl = ''
    },

    openCropDialog() {
      if (!this.previewUrl) return
      this.cropImageSrc = this.previewUrl
      this.scaleValue = 100
      this.cropDialogVisible = true
    }
  }
}
</script>

<style lang="scss">
.form-component-avatar-upload-edit {
  .avatar-uploader-wrapper {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;

    &.is-disabled {
      pointer-events: none;
      opacity: 0.6;
    }
  }

  .avatar-preview-zone {
    position: relative;
    width: 100px;
    height: 100px;
    border-radius: 50%;
    overflow: hidden;
    border: 2px dashed #dcdfe6;
    cursor: pointer;
    transition: border-color 0.3s;

    &:hover {
      border-color: #409EFF;
      .avatar-hover-overlay {
        opacity: 1;
      }
    }
  }

  .avatar-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .avatar-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #fafafa;
  }

  .avatar-icon {
    font-size: 28px;
    color: #c0c4cc;
  }

  .avatar-hover-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: opacity 0.3s;
    border-radius: 50%;
  }

  .overlay-text {
    color: #fff;
    font-size: 12px;
  }

  .upload-tip-text {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .tip-label {
    font-size: 12px;
    color: #909399;
  }

  .avatar-action-btns {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
}

// 裁剪弹窗样式
.crop-container {
  display: flex;
  gap: 20px;
  height: 400px;

  .crop-area {
    flex: 1;
    overflow: hidden;
    background: #f0f0f0;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;

    canvas, .crop-target-image {
      max-width: 100%;
      max-height: 100%;
      display: block;
    }
  }

  .crop-preview-wrapper {
    width: 140px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding-top: 10px;
  }

  .preview-label {
    font-size: 13px;
    color: #606266;
    margin: 0;
  }

  .crop-preview-circle {
    border-radius: 50%;
    overflow: hidden;
    border: 2px solid #dcdfe6;
    flex-shrink: 0;
    background: #fafafa;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .preview-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .scale-control {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: #606266;

    .el-slider {
      flex: 1;
    }

    .scale-value {
      width: 36px;
      text-align: right;
    }
  }
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>

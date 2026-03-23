<template>
  <div class="map-dispatch-page">
    <!-- 左侧工单列表区域 -->
    <div class="left-panel">
      <div class="panel-header">
        <span class="panel-title">工单列表</span>
        <span class="work-order-count">共 {{ workOrders.length }} 条</span>
      </div>

      <!-- 筛选区域 -->
      <div class="filter-section">
        <el-select
          v-model="filterForm.status"
          placeholder="工单状态"
          size="small"
          clearable
          style="width: 120px"
          @change="handleFilterChange"
        >
          <el-option label="待派单" value="pending" />
          <el-option label="已派单" value="assigned" />
          <el-option label="处理中" value="processing" />
          <el-option label="已完成" value="completed" />
        </el-select>
        <el-input
          v-model="filterForm.keyword"
          placeholder="搜索工单"
          size="small"
          clearable
          style="width: 140px"
          @input="handleFilterChange"
        >
          <i slot="prefix" class="el-input__icon el-icon-search" />
        </el-input>
      </div>

      <!-- 工单列表 -->
      <div class="work-order-list" ref="orderListRef">
        <div
          v-for="order in filteredOrders"
          :key="order.id"
          :class="['work-order-item', { active: selectedOrder && selectedOrder.id === order.id }]"
          @click="handleOrderClick(order)"
        >
          <div class="order-header">
            <span class="order-title">{{ order.title || order.name || '工单-' + order.id }}</span>
            <span :class="['order-status', `status-${order.status}`]">
              {{ getStatusText(order.status) }}
            </span>
          </div>
          <div class="order-info">
            <span class="order-address" v-if="order.address">
              <i class="el-icon-location" />
              {{ order.address }}
            </span>
          </div>
          <div class="order-meta">
            <span class="order-time" v-if="order.createTime">
              {{ formatTime(order.createTime) }}
            </span>
            <span class="order-handler" v-if="order.handlerName">
              处理人：{{ order.handlerName }}
            </span>
          </div>
        </div>

        <div v-if="filteredOrders.length === 0" class="empty-list">
          <i class="el-icon-document" />
          <span>暂无工单数据</span>
        </div>
      </div>
    </div>

    <!-- 右侧地图区域 -->
    <div class="right-panel">
      <div id="amap-container" class="map-container" />

      <!-- 地图工具栏 -->
      <div class="map-toolbar">
        <el-button-group>
          <el-button size="small" icon="el-icon-plus" @click="zoomIn" title="放大" />
          <el-button size="small" icon="el-icon-minus" @click="zoomOut" title="缩小" />
          <el-button size="small" icon="el-icon-location" @click="centerOnMarkers" title="居中" />
        </el-button-group>
      </div>
    </div>

    <!-- 工单详情/派单弹窗 -->
    <el-dialog
      :title="dialogTitle"
      :visible.sync="dialogVisible"
      width="500px"
      :before-close="handleDialogClose"
    >
      <div class="order-detail" v-if="selectedOrder">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="工单编号">
            {{ selectedOrder.id }}
          </el-descriptions-item>
          <el-descriptions-item label="工单标题">
            {{ selectedOrder.title || selectedOrder.name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="工单状态">
            <el-tag :type="getStatusTagType(selectedOrder.status)" size="small">
              {{ getStatusText(selectedOrder.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="地址" v-if="selectedOrder.address">
            {{ selectedOrder.address }}
          </el-descriptions-item>
          <el-descriptions-item label="描述" v-if="selectedOrder.description">
            {{ selectedOrder.description }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间" v-if="selectedOrder.createTime">
            {{ formatTime(selectedOrder.createTime) }}
          </el-descriptions-item>
          <el-descriptions-item label="当前处理人" v-if="selectedOrder.handlerName">
            {{ selectedOrder.handlerName }}
          </el-descriptions-item>
        </el-descriptions>

        <!-- 派单操作区域 -->
        <div class="dispatch-section" v-if="showDispatchSection">
          <h4 class="dispatch-title">派单操作</h4>
          <el-form :model="dispatchForm" label-width="80px" size="small">
            <el-form-item label="处理人">
              <el-select
                v-model="dispatchForm.handlerId"
                placeholder="请选择处理人"
                filterable
                style="width: 100%"
                @focus="loadHandlers"
              >
                <el-option
                  v-for="handler in handlers"
                  :key="handler.id"
                  :label="handler.name"
                  :value="handler.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="派单备注">
              <el-input
                v-model="dispatchForm.remark"
                type="textarea"
                :rows="3"
                placeholder="请输入派单备注"
              />
            </el-form-item>
          </el-form>
        </div>
      </div>

      <span slot="footer" class="dialog-footer">
        <el-button @click="dialogVisible = false">取 消</el-button>
        <el-button type="primary" @click="handleDispatch" :loading="dispatchLoading" v-if="showDispatchSection">
          确 定 派 单
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
/* global AMap */
import Api, { FORM_IDS, TAB_IDS } from '../api';

export default {
  name: 'apaas-custom-map-view',

  data() {
    return {
      // 工单列表
      workOrders: [],
      // 筛选条件
      filterForm: {
        status: '',
        keyword: '',
      },
      // 选中的工单
      selectedOrder: null,
      // 地图实例
      map: null,
      markers: [],
      // 弹窗
      dialogVisible: false,
      dialogTitle: '工单详情',
      // 派单
      dispatchLoading: false,
      dispatchForm: {
        handlerId: '',
        remark: '',
      },
      handlers: [],
    };
  },

  computed: {
    // 筛选后的工单列表
    filteredOrders() {
      let result = this.workOrders;

      if (this.filterForm.status) {
        result = result.filter(order => order.status === this.filterForm.status);
      }

      if (this.filterForm.keyword) {
        const keyword = this.filterForm.keyword.toLowerCase();
        result = result.filter(order => {
          const title = (order.title || order.name || '').toLowerCase();
          const address = (order.address || '').toLowerCase();
          return title.includes(keyword) || address.includes(keyword);
        });
      }

      return result;
    },

    // 是否显示派单区域
    showDispatchSection() {
      return this.selectedOrder && this.selectedOrder.status !== 'completed';
    },
  },

  created() {
    this.loadWorkOrders();
  },

  mounted() {
    this.initMap();
  },

  beforeDestroy() {
    if (this.map) {
      this.map.destroy();
    }
  },

  methods: {
    // 加载工单列表
    loadWorkOrders() {
      this.$request({
        ...Api.QUERY_LIST,
        data: {
          formId: FORM_IDS.WORK_ORDER,
          tabId: TAB_IDS.WORK_ORDER,
          page: 1,
          pageSize: 500, // 地图展示尽量多加载
        },
      })
        .asyncThen((resp) => {
          this.workOrders = resp && resp.data ? resp.data : [];
          this.renderMarkers();
        })
        .asyncErrorCatch((error) => {
          console.error('加载工单失败:', error);
          this.$message.error('加载工单数据失败');
        });
    },

    // 初始化地图
    initMap() {
      // 检查 AMap 是否可用
      if (typeof AMap === 'undefined') {
        console.warn('高德地图 SDK 未加载，请在 public/index.html 中配置');
        return;
      }

      this.map = new AMap.Map('amap-container', {
        zoom: 11,
        center: [116.397428, 39.90923], // 默认中心点（北京）
        resizeEnable: true,
      });

      // 地图加载完成后渲染标记
      this.map.on('complete', () => {
        this.renderMarkers();
      });
    },

    // 渲染地图标记
    renderMarkers() {
      if (!this.map || typeof AMap === 'undefined') return;

      // 清除旧标记
      if (this.markers.length > 0) {
        this.map.remove(this.markers);
        this.markers = [];
      }

      const ordersWithLocation = this.filteredOrders.filter(order => {
        // 支持多种经纬度字段名
        const lng = order.longitude || order.lng || order.longitude_;
        const lat = order.latitude || order.lat || order.latitude_;
        return lng && lat && !isNaN(parseFloat(lng)) && !isNaN(parseFloat(lat));
      });

      if (ordersWithLocation.length === 0) {
        return;
      }

      ordersWithLocation.forEach(order => {
        const lng = parseFloat(order.longitude || order.lng || order.longitude_);
        const lat = parseFloat(order.latitude || order.lat || order.latitude_);

        const marker = new AMap.Marker({
          position: new AMap.LngLat(lng, lat),
          title: order.title || order.name || order.id,
          // 根据状态设置不同颜色
          extData: order,
        });

        // 点击标记
        marker.on('click', () => {
          this.handleOrderClick(order);
        });

        this.markers.push(marker);
        this.map.add(marker);
      });

      // 自动调整视野
      if (this.markers.length > 0) {
        this.map.setFitView(this.markers);
      }
    },

    // 处理筛选变化
    handleFilterChange() {
      // 延迟执行，等待筛选结果
      this.$nextTick(() => {
        this.renderMarkers();
      });
    },

    // 点击工单
    handleOrderClick(order) {
      this.selectedOrder = order;
      this.dialogTitle = '工单详情';
      this.dialogVisible = true;
      this.dispatchForm = { handlerId: '', remark: '' };

      // 如果有坐标，地图中心移动到该位置
      if (this.map) {
        const lng = parseFloat(order.longitude || order.lng || order.longitude_);
        const lat = parseFloat(order.latitude || order.lat || order.latitude_);
        if (lng && lat) {
          this.map.setCenter([lng, lat]);
          this.map.setZoom(15);
        }
      }
    },

    // 关闭弹窗
    handleDialogClose() {
      this.dialogVisible = false;
    },

    // 加载处理人列表
    loadHandlers() {
      // TODO: 替换为实际的处理人接口
      // 这里使用模拟数据
      if (this.handlers.length === 0) {
        this.handlers = [
          { id: 'user1', name: '张三' },
          { id: 'user2', name: '李四' },
          { id: 'user3', name: '王五' },
        ];
      }
    },

    // 执行派单
    handleDispatch() {
      if (!this.dispatchForm.handlerId) {
        this.$message.warning('请选择处理人');
        return;
      }

      this.dispatchLoading = true;

      // TODO: 替换为实际的派单接口
      // 这里模拟派单操作
      this.$request({
        ...Api.UPDATE_WORK_ORDER,
        data: {
          formId: FORM_IDS.WORK_ORDER,
          id: this.selectedOrder.id,
          data: {
            status: 'assigned',
            handlerId: this.dispatchForm.handlerId,
            handlerName: this.handlers.find(h => h.id === this.dispatchForm.handlerId)?.name || '',
            dispatchRemark: this.dispatchForm.remark,
            dispatchTime: new Date().toISOString(),
          },
        },
      })
        .asyncThen(() => {
          this.$message.success('派单成功');
          this.dialogVisible = false;
          // 更新本地数据
          if (this.selectedOrder) {
            const handler = this.handlers.find(h => h.id === this.dispatchForm.handlerId);
            this.selectedOrder.status = 'assigned';
            this.selectedOrder.handlerId = this.dispatchForm.handlerId;
            this.selectedOrder.handlerName = handler?.name || '';
          }
          this.dispatchLoading = false;
        })
        .asyncErrorCatch((error) => {
          console.error('派单失败:', error);
          this.$message.error('派单失败');
          this.dispatchLoading = false;
        });
    },

    // 获取状态文本
    getStatusText(status) {
      const statusMap = {
        pending: '待派单',
        assigned: '已派单',
        processing: '处理中',
        completed: '已完成',
        cancel: '已取消',
      };
      return statusMap[status] || status || '未知';
    },

    // 获取状态标签类型
    getStatusTagType(status) {
      const typeMap = {
        pending: 'warning',
        assigned: 'primary',
        processing: 'info',
        completed: 'success',
        cancel: 'info',
      };
      return typeMap[status] || 'info';
    },

    // 格式化时间
    formatTime(time) {
      if (!time) return '';
      if (typeof time === 'string') {
        return this.$dayjs(time).format('YYYY-MM-DD HH:mm');
      }
      return this.$dayjs(time).format('YYYY-MM-DD HH:mm');
    },

    // 地图操作
    zoomIn() {
      if (this.map) {
        this.map.zoomIn();
      }
    },

    zoomOut() {
      if (this.map) {
        this.map.zoomOut();
      }
    },

    centerOnMarkers() {
      if (this.map && this.markers.length > 0) {
        this.map.setFitView(this.markers);
      }
    },
  },
};
</script>

<style lang="scss" scoped>
.map-dispatch-page {
  height: 100%;
  width: 100%;
  box-sizing: border-box;
  display: flex;
  overflow: hidden;
  background: #f5f7fa;
}

/* 左侧工单列表 */
.left-panel {
  width: 360px;
  min-width: 300px;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;

  .panel-header {
    padding: 16px;
    border-bottom: 1px solid #e4e7ed;
    display: flex;
    justify-content: space-between;
    align-items: center;

    .panel-title {
      font-size: 16px;
      font-weight: 600;
      color: #303133;
    }

    .work-order-count {
      font-size: 12px;
      color: #909399;
    }
  }

  .filter-section {
    padding: 12px 16px;
    border-bottom: 1px solid #e4e7ed;
    display: flex;
    gap: 8px;
  }

  .work-order-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px;

    .work-order-item {
      padding: 12px;
      margin-bottom: 8px;
      border: 1px solid #e4e7ed;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.3s;

      &:hover {
        border-color: #409eff;
        box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
      }

      &.active {
        border-color: #409eff;
        background: #ecf5ff;
      }

      .order-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;

        .order-title {
          font-size: 14px;
          font-weight: 500;
          color: #303133;
          flex: 1;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .order-status {
          font-size: 12px;
          padding: 2px 8px;
          border-radius: 3px;
          margin-left: 8px;
          flex-shrink: 0;

          &.status-pending {
            background: #fff7e6;
            color: #faad14;
          }

          &.status-assigned {
            background: #e6f7ff;
            color: #1890ff;
          }

          &.status-processing {
            background: #f0f0f0;
            color: #666;
          }

          &.status-completed {
            background: #f6ffed;
            color: #52c41a;
          }
        }
      }

      .order-info {
        margin-bottom: 8px;

        .order-address {
          font-size: 12px;
          color: #909399;
          display: flex;
          align-items: center;
          gap: 4px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;

          i {
            flex-shrink: 0;
          }
        }
      }

      .order-meta {
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        color: #c0c4cc;

        .order-handler {
          color: #409eff;
        }
      }
    }

    .empty-list {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px 0;
      color: #909399;

      i {
        font-size: 48px;
        margin-bottom: 12px;
      }
    }
  }
}

/* 右侧地图区域 */
.right-panel {
  flex: 1;
  position: relative;

  .map-container {
    width: 100%;
    height: 100%;
  }

  .map-toolbar {
    position: absolute;
    top: 16px;
    right: 16px;
    background: #fff;
    padding: 4px;
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  }
}

/* 弹窗样式 */
.order-detail {
  .dispatch-section {
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid #e4e7ed;

    .dispatch-title {
      margin: 0 0 16px 0;
      font-size: 14px;
      font-weight: 500;
      color: #303133;
    }
  }
}
</style>

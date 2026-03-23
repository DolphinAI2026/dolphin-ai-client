<template>
  <div class="apaas-custom-map-view">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <span class="page-title">地图派工</span>
        <span v-if="statistics.pendingCount > 0" class="stat-badge">
          <span class="stat-dot stat-dot--pending" />
          待派工 {{ statistics.pendingCount }}
        </span>
        <span v-if="statistics.processingCount > 0" class="stat-badge">
          <span class="stat-dot stat-dot--processing" />
          处理中 {{ statistics.processingCount }}
        </span>
      </div>
      <div class="toolbar-right">
        <el-select
          v-model="filterForm.orderStatus"
          placeholder="工单状态"
          size="small"
          clearable
          style="width: 120px"
          @change="handleQuery"
        >
          <el-option label="待派工" value="pending" />
          <el-option label="已派工" value="dispatched" />
          <el-option label="处理中" value="processing" />
          <el-option label="已完成" value="completed" />
        </el-select>
        <el-select
          v-model="filterForm.personStatus"
          placeholder="人员状态"
          size="small"
          clearable
          style="width: 120px"
          @change="handleQuery"
        >
          <el-option label="空闲" value="idle" />
          <el-option label="工作中" value="working" />
          <el-option label="离线" value="offline" />
        </el-select>
        <el-input
          v-model="filterForm.keyword"
          placeholder="搜索工单/人员"
          size="small"
          clearable
          style="width: 180px"
          @keyup.enter.native="handleQuery"
        >
          <i slot="prefix" class="el-input__icon el-icon-search" />
        </el-input>
        <el-button type="primary" size="small" icon="el-icon-refresh" :loading="loading" @click="handleQuery">
          刷新
        </el-button>
      </div>
    </div>

    <!-- 主体内容区 -->
    <div class="main-content">
      <!-- 左侧工单列表 -->
      <div class="left-panel">
        <div class="panel-header">
          <span class="panel-title">工单列表</span>
          <span class="panel-count">{{ filteredOrders.length }} 条</span>
        </div>
        <div class="panel-body" @scroll="handleLeftPanelScroll">
          <div v-if="loading && orderList.length === 0" class="loading-state">
            <i class="el-icon-loading" />
            <span>加载中...</span>
          </div>
          <template v-else>
            <div
              v-for="order in filteredOrders"
              :key="order.id"
              class="order-item"
              :class="{ 'is-selected': selectedOrder && selectedOrder.id === order.id }"
              @click="selectOrder(order)"
            >
              <div class="order-header">
                <span class="order-name">{{ order.title }}</span>
                <span class="order-status" :class="'status-' + order.status">
                  {{ getStatusText(order.status) }}
                </span>
              </div>
              <div class="order-info">
                <span class="order-address" :title="order.address">
                  <i class="el-icon-location" />
                  {{ order.address }}
                </span>
                <span class="order-priority" :class="'priority-' + order.priority">
                  {{ getPriorityText(order.priority) }}
                </span>
              </div>
              <div class="order-meta">
                <span class="order-time">{{ order.createTime }}</span>
                <span v-if="order.assignedName" class="order-assignee">
                  <i class="el-icon-user" />
                  {{ order.assignedName }}
                </span>
              </div>
            </div>
            <div v-if="!loading && filteredOrders.length === 0" class="empty-state">
              <i class="el-icon-folder-delete" />
              <span>暂无工单</span>
            </div>
          </template>
        </div>
      </div>

      <!-- 中间地图 -->
      <div class="map-container" id="map-container">
        <div id="amap" class="amap" />
        <!-- 地图图例 -->
        <div class="map-legend">
          <div class="legend-item">
            <span class="legend-marker legend-marker--order" />
            <span>工单</span>
          </div>
          <div class="legend-item">
            <span class="legend-marker legend-marker--person" />
            <span>人员</span>
          </div>
          <div class="legend-item">
            <span class="legend-marker legend-marker--selected" />
            <span>已选</span>
          </div>
        </div>
        <!-- 地图操作 -->
        <div class="map-actions">
          <el-button-group>
            <el-button size="small" icon="el-icon-zoom-in" title="放大" @click="zoomIn" />
            <el-button size="small" icon="el-icon-zoom-out" title="缩小" @click="zoomOut" />
            <el-button size="small" icon="el-icon-full-screen" title="全屏" @click="toggleFullscreen" />
            <el-button
              v-if="selectedOrder && selectedPerson"
              size="small"
              icon="el-icon-guide"
              title="规划路线"
              type="primary"
              @click="drawRoute"
            >
              路线
            </el-button>
          </el-button-group>
        </div>
        <!-- 加载地图遮罩 -->
        <div v-if="mapLoading" class="map-loading-mask">
          <i class="el-icon-loading map-loading-icon" />
          <span>地图加载中...</span>
        </div>
      </div>

      <!-- 右侧人员列表 -->
      <div class="right-panel">
        <div class="panel-header">
          <span class="panel-title">可选人员</span>
          <span class="panel-count">{{ filteredPersons.length }} 人</span>
        </div>
        <div class="panel-body">
          <div v-if="loading && personList.length === 0" class="loading-state">
            <i class="el-icon-loading" />
            <span>加载中...</span>
          </div>
          <template v-else>
            <div
              v-for="person in filteredPersons"
              :key="person.id"
              class="person-item"
              :class="{
                'is-selected': selectedPerson && selectedPerson.id === person.id,
                'is-offline': person.status === 'offline'
              }"
              @click="selectPerson(person)"
            >
              <div class="person-avatar" :class="'avatar--' + person.status">
                <i class="el-icon-user-solid" />
              </div>
              <div class="person-info">
                <div class="person-name">{{ person.name }}
                  <span v-if="person.phone" class="person-phone">{{ person.phone }}</span>
                </div>
                <div class="person-meta">
                  <span class="person-status" :class="'status-' + person.status">
                    {{ getPersonStatusText(person.status) }}
                  </span>
                  <span v-if="person.currentTask" class="person-task" :title="person.currentTask">
                    {{ person.currentTask }}
                  </span>
                </div>
                <div v-if="person.distance !== null && person.distance !== undefined" class="person-distance">
                  <i class="el-icon-location" />
                  <span v-if="person.distance >= 1">{{ person.distance.toFixed(1) }}km</span>
                  <span v-else>{{ Math.round(person.distance * 1000) }}m</span>
                  <span v-if="person.eta" class="person-eta">· 约{{ person.eta }}分钟</span>
                </div>
              </div>
            </div>
            <div v-if="!loading && filteredPersons.length === 0" class="empty-state">
              <i class="el-icon-user" />
              <span>暂无人员</span>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 底部派工栏 -->
    <div class="dispatch-bar">
      <div class="dispatch-info">
        <template v-if="selectedOrder || selectedPerson">
          <transition-group name="fade-tip">
            <span v-if="selectedOrder" :key="'order'" class="dispatch-tip dispatch-tip--order">
              <i class="el-icon-document" />
              已选工单：<strong>{{ selectedOrder.title }}</strong>
            </span>
            <span v-if="selectedPerson" :key="'person'" class="dispatch-tip dispatch-tip--person">
              <i class="el-icon-user" />
              派工给：<strong>{{ selectedPerson.name }}</strong>
              <span v-if="selectedPerson.distance !== null && selectedPerson.distance !== undefined" class="tip-distance">
                ({{ selectedPerson.distance >= 1 ? selectedPerson.distance.toFixed(1) + 'km' : Math.round(selectedPerson.distance * 1000) + 'm' }})
              </span>
            </span>
          </transition-group>
        </template>
        <span v-else class="dispatch-hint">
          <i class="el-icon-info" />
          点击地图上的标记或列表项选择工单和人员
        </span>
      </div>
      <div class="dispatch-actions">
        <el-button size="small" :disabled="!selectedOrder && !selectedPerson" @click="clearSelection">
          清空选择
        </el-button>
        <el-button
          type="primary"
          size="small"
          :disabled="!selectedOrder || !selectedPerson || dispatching"
          :loading="dispatching"
          @click="handleDispatch"
        >
          <i v-if="!dispatching" class="el-icon-s-promotion" />
          确认派工
        </el-button>
      </div>
    </div>

    <!-- 派工成功提示 -->
    <el-dialog
      title="派工成功"
      :visible.sync="dispatchSuccessVisible"
      width="420px"
      center
      :close-on-click-modal="false"
    >
      <div class="dispatch-result">
        <i class="el-icon-success dispatch-icon" />
        <p>工单已成功派发给 <strong>{{ selectedPerson ? selectedPerson.name : '' }}</strong></p>
        <p class="dispatch-detail">
          <template v-if="selectedPerson && selectedPerson.eta">
            预计 {{ selectedPerson.eta }} 分钟到达工单地点
          </template>
          <template v-else>
            人员已收到派工通知
          </template>
        </p>
        <div class="dispatch-order-info">
          <div class="dispatch-info-item">
            <span class="info-label">工单</span>
            <span class="info-value">{{ selectedOrder ? selectedOrder.title : '' }}</span>
          </div>
          <div class="dispatch-info-item">
            <span class="info-label">地址</span>
            <span class="info-value">{{ selectedOrder ? selectedOrder.address : '' }}</span>
          </div>
        </div>
      </div>
      <span slot="footer">
        <el-button type="primary" @click="handleDispatchSuccessConfirm">确定</el-button>
      </span>
    </el-dialog>

    <!-- 人员详情弹窗 -->
    <el-dialog
      :visible.sync="personDetailVisible"
      :title="personDetail.name + ' - 详情'"
      width="450px"
    >
      <div v-if="personDetail" class="person-detail">
        <div class="detail-row">
          <span class="detail-label">姓名</span>
          <span class="detail-value">{{ personDetail.name }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">电话</span>
          <span class="detail-value">
            <a v-if="personDetail.phone" :href="'tel:' + personDetail.phone">{{ personDetail.phone }}</a>
            <span v-else class="text-muted">--</span>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">状态</span>
          <span class="detail-value">
            <span class="person-status" :class="'status-' + personDetail.status">
              {{ getPersonStatusText(personDetail.status) }}
            </span>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">当前位置</span>
          <span class="detail-value">
            <span v-if="personDetail.address">{{ personDetail.address }}</span>
            <span v-else class="text-muted">--</span>
          </span>
        </div>
        <div v-if="personDetail.currentTask" class="detail-row">
          <span class="detail-label">当前任务</span>
          <span class="detail-value">{{ personDetail.currentTask }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">今日已完成</span>
          <span class="detail-value">{{ personDetail.completedToday || 0 }} 单</span>
        </div>
      </div>
    </el-dialog>

    <!-- 工单详情弹窗 -->
    <el-dialog
      :visible.sync="orderDetailVisible"
      :title="orderDetail.title"
      width="500px"
    >
      <div v-if="orderDetail" class="order-detail">
        <div class="detail-row">
          <span class="detail-label">工单编号</span>
          <span class="detail-value">{{ orderDetail.id }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">工单标题</span>
          <span class="detail-value">{{ orderDetail.title }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">工单状态</span>
          <span class="detail-value">
            <span class="order-status" :class="'status-' + orderDetail.status">
              {{ getStatusText(orderDetail.status) }}
            </span>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">优先级</span>
          <span class="detail-value">
            <span class="order-priority" :class="'priority-' + orderDetail.priority">
              {{ getPriorityText(orderDetail.priority) }}
            </span>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">工单地址</span>
          <span class="detail-value">{{ orderDetail.address }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">创建时间</span>
          <span class="detail-value">{{ orderDetail.createTime }}</span>
        </div>
        <div v-if="orderDetail.assignedName" class="detail-row">
          <span class="detail-label">派给</span>
          <span class="detail-value">{{ orderDetail.assignedName }}</span>
        </div>
        <div v-if="orderDetail.description" class="detail-row detail-row--block">
          <span class="detail-label">工单描述</span>
          <span class="detail-value">{{ orderDetail.description }}</span>
        </div>
      </div>
      <span slot="footer">
        <el-button @click="orderDetailVisible = false">关闭</el-button>
        <el-button
          v-if="orderDetail && orderDetail.status === 'pending'"
          type="primary"
          @click="handleDispatchFromDetail"
        >
          去派工
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
/* global AMap */

import Api from '../api/index.js'

export default {
  name: 'apaas-custom-map-view',

  data() {
    return {
      // 筛选条件
      filterForm: {
        orderStatus: '',
        personStatus: '',
        keyword: '',
      },

      // 工单列表
      orderList: [],
      // 人员列表
      personList: [],
      // 选中的工单
      selectedOrder: null,
      // 选中的人员
      selectedPerson: null,

      // 加载状态
      loading: false,
      dispatching: false,
      mapLoading: true,

      // 地图实例
      map: null,
      // AMap 服务
      driving: null,
      // 工单标记
      orderMarkers: [],
      // 人员标记
      personMarkers: [],
      // 路线覆盖物
      routeOverlays: [],
      // 信息窗体
      currentInfoWindow: null,

      // 派工成功弹窗
      dispatchSuccessVisible: false,

      // 人员详情弹窗
      personDetail: null,
      personDetailVisible: false,

      // 工单详情弹窗
      orderDetail: null,
      orderDetailVisible: false,

      // 定时刷新
      refreshTimer: null,
    }
  },

  computed: {
    // 统计数据
    statistics() {
      return {
        pendingCount: this.orderList.filter(o => o.status === 'pending').length,
        processingCount: this.orderList.filter(o => o.status === 'processing').length,
      }
    },

    // 过滤后的工单列表
    filteredOrders() {
      let list = this.orderList
      if (this.filterForm.orderStatus) {
        list = list.filter(o => o.status === this.filterForm.orderStatus)
      }
      if (this.filterForm.keyword) {
        const kw = this.filterForm.keyword.toLowerCase()
        list = list.filter(o =>
          (o.title && o.title.toLowerCase().includes(kw)) ||
          (o.address && o.address.toLowerCase().includes(kw)) ||
          (o.id && o.id.toLowerCase().includes(kw))
        )
      }
      return list
    },

    // 过滤后的人员列表
    filteredPersons() {
      let list = this.personList
      if (this.filterForm.personStatus) {
        list = list.filter(p => p.status === this.filterForm.personStatus)
      }
      if (this.filterForm.keyword) {
        const kw = this.filterForm.keyword.toLowerCase()
        list = list.filter(p =>
          (p.name && p.name.toLowerCase().includes(kw))
        )
      }
      // 按距离排序（null/undefined 排最后）
      return [...list].sort((a, b) => {
        const da = a.distance == null ? 9999 : a.distance
        const db = b.distance == null ? 9999 : b.distance
        return da - db
      })
    },
  },

  mounted() {
    this.initMap()
  },

  beforeDestroy() {
    this.stopAutoRefresh()
    if (this.map) {
      this.map.destroy()
    }
  },

  methods: {
    // ==========================================
    // 地图初始化
    // ==========================================

    initMap() {
      this.$nextTick(() => {
        const checkAMap = () => {
          if (typeof AMap === 'undefined') {
            setTimeout(checkAMap, 500)
            return
          }
          this.mapLoading = false
          this.initAMap()
        }
        checkAMap()
      })
    },

    initAMap() {
      const container = document.getElementById('amap')
      if (!container) return

      this.map = new AMap.Map('amap', {
        zoom: 12,
        center: [116.397428, 39.90923],
        mapStyle: 'amap://styles/normal',
        resizeEnable: true,
      })

      // 初始化驾车路线规划
      this.driving = new AMap.Driving({
        map: this.map,
        panel: null,
        autoFitView: false,
      })

      // 地图加载完成
      this.map.on('complete', () => {
        this.mapLoading = false
        this.loadData()
      })

      // 监听地图点击，关闭信息窗体
      this.map.on('click', () => {
        this.closeInfoWindow()
      })

      // 监听窗口 resize
      window.addEventListener('resize', this.handleMapResize)
    },

    handleMapResize() {
      if (this.map) {
        this.map.resize()
      }
    },

    // ==========================================
    // 数据加载
    // ==========================================

    loadData() {
      this.loadOrders()
      this.loadPersons()
      this.startAutoRefresh()
    },

    // 加载工单列表
    loadOrders() {
      this.loading = true
      const useMock = !this.isRealApiAvailable()

      if (useMock) {
        setTimeout(() => {
          this.orderList = this.getMockOrders()
          this.loading = false
          this.renderMarkers()
        }, 300)
        return
      }

      this.$request({
        ...Api.QUERY_ORDERS,
        data: {
          status: this.filterForm.orderStatus || undefined,
          keyword: this.filterForm.keyword || undefined,
        }
      }).asyncThen(res => {
        this.orderList = (res.data && Array.isArray(res.data)) ? res.data : []
        this.loading = false
        this.renderMarkers()
      }).asyncErrorCatch(() => {
        this.$message.error('加载工单列表失败')
        this.loading = false
      })
    },

    // 加载人员列表
    loadPersons() {
      const useMock = !this.isRealApiAvailable()

      if (useMock) {
        setTimeout(() => {
          this.personList = this.getMockPersons()
        }, 200)
        return
      }

      this.$request({
        ...Api.QUERY_PERSONS,
        data: {
          status: this.filterForm.personStatus || undefined,
        }
      }).asyncThen(res => {
        this.personList = (res.data && Array.isArray(res.data)) ? res.data : []
      }).asyncErrorCatch(() => {
        this.$message.error('加载人员列表失败')
      })
    },

    isRealApiAvailable() {
      // 检测是否为真实 API，如果是 mock 环境则使用 mock 数据
      // TODO: 替换为实际 API 时返回 true
      return false
    },

    // ==========================================
    // Mock 数据
    // ==========================================

    getMockOrders() {
      return [
        {
          id: 'order-001',
          title: '电梯故障维修',
          address: '朝阳区建国路88号',
          position: [116.477428, 39.91923],
          status: 'pending',
          priority: 'high',
          createTime: '2026-03-23 09:30',
          assignedName: null,
          phone: '010-12345601',
          description: '电梯无法正常运行，有人员被困，请紧急处理。',
          reporter: '物业管理员',
        },
        {
          id: 'order-002',
          title: '空调不制冷',
          address: '海淀区中关村大街1号',
          position: [116.317428, 39.98923],
          status: 'pending',
          priority: 'medium',
          createTime: '2026-03-23 10:15',
          assignedName: null,
          phone: '010-12345602',
          description: '3楼办公室空调不制冷。',
          reporter: '行政部',
        },
        {
          id: 'order-003',
          title: '水管漏水',
          address: '东城区王府井大街100号',
          position: [116.407428, 39.92923],
          status: 'dispatched',
          priority: 'high',
          createTime: '2026-03-23 08:45',
          assignedName: '张三',
          phone: '010-12345603',
          description: '卫生间水管漏水严重。',
          reporter: '保洁员',
        },
        {
          id: 'order-004',
          title: '门锁损坏',
          address: '西城区西单北大街120号',
          position: [116.377428, 39.93923],
          status: 'processing',
          priority: 'low',
          createTime: '2026-03-23 07:20',
          assignedName: '李四',
          phone: '010-12345604',
          description: '会议室门锁损坏，无法上锁。',
          reporter: '前台',
        },
        {
          id: 'order-005',
          title: '电路短路',
          address: '朝阳区望京SOHO',
          position: [116.477428, 39.99923],
          status: 'pending',
          priority: 'high',
          createTime: '2026-03-23 11:00',
          assignedName: null,
          phone: '010-12345605',
          description: '办公室电路跳闸，无法送电。',
          reporter: 'IT部门',
        },
        {
          id: 'order-006',
          title: '窗户玻璃破损',
          address: '海淀区清华科技园',
          position: [116.317428, 39.99923],
          status: 'pending',
          priority: 'medium',
          createTime: '2026-03-23 11:30',
          assignedName: null,
          phone: '010-12345606',
          description: '12层窗户玻璃有裂缝，需要更换。',
          reporter: '安全员',
        },
        {
          id: 'order-007',
          title: '照明灯管更换',
          address: '朝阳区三里屯SOHO',
          position: [116.447428, 39.93923],
          status: 'completed',
          priority: 'low',
          createTime: '2026-03-23 08:00',
          assignedName: '王五',
          phone: '010-12345607',
          description: '走廊灯管闪烁需要更换。',
          reporter: '物业',
        },
      ]
    },

    getMockPersons() {
      return [
        {
          id: 'person-001',
          name: '张三',
          phone: '13800001001',
          position: [116.457428, 39.92923],
          address: '朝阳区CBD附近',
          status: 'idle',
          currentTask: null,
          distance: null,
          eta: null,
          completedToday: 3,
        },
        {
          id: 'person-002',
          name: '李四',
          phone: '13800001002',
          position: [116.387428, 39.94923],
          address: '西城区金融街',
          status: 'working',
          currentTask: '门锁损坏',
          distance: null,
          eta: null,
          completedToday: 5,
        },
        {
          id: 'person-003',
          name: '王五',
          phone: '13800001003',
          position: [116.507428, 39.89923],
          address: '朝阳区四惠附近',
          status: 'idle',
          currentTask: null,
          distance: null,
          eta: null,
          completedToday: 4,
        },
        {
          id: 'person-004',
          name: '赵六',
          phone: '13800001004',
          position: [116.327428, 39.95923],
          address: '海淀区上地',
          status: 'offline',
          currentTask: null,
          distance: null,
          eta: null,
          completedToday: 0,
        },
        {
          id: 'person-005',
          name: '钱七',
          phone: '13800001005',
          position: [116.397428, 39.95923],
          address: '东城区东直门',
          status: 'idle',
          currentTask: null,
          distance: null,
          eta: null,
          completedToday: 2,
        },
      ]
    },

    // ==========================================
    // 地图标记渲染
    // ==========================================

    renderMarkers() {
      if (!this.map) return

      // 清除旧标记和路线
      this.clearAllOverlays()

      // 渲染工单标记
      this.orderList.forEach(order => {
        if (!order.position) return
        const marker = this.createOrderMarker(order)
        this.orderMarkers.push(marker)
        this.map.add(marker)
      })

      // 渲染人员标记
      this.personList.forEach(person => {
        if (!person.position) return
        const marker = this.createPersonMarker(person)
        this.personMarkers.push(marker)
        this.map.add(marker)
      })

      // 自适应显示所有标记
      if (this.orderMarkers.length > 0 || this.personMarkers.length > 0) {
        setTimeout(() => {
          if (this.map) {
            this.map.setFitView()
          }
        }, 100)
      }
    },

    createOrderMarker(order) {
      const isSelected = this.selectedOrder && this.selectedOrder.id === order.id
      const isPending = order.status === 'pending'
      const isHigh = order.priority === 'high'

      // 不同状态的颜色
      const colorMap = {
        pending: isHigh ? '#f56c6c' : '#e6a23c',
        dispatched: '#409eff',
        processing: '#409eff',
        completed: '#67c23a',
      }
      const color = isSelected ? '#67c23a' : colorMap[order.status] || '#909399'

      const marker = new AMap.Marker({
        position: order.position,
        title: order.title,
        content: this.createMarkerContent('order', color, isSelected, order.title),
        offset: new AMap.Pixel(0, -20),
        extData: { type: 'order', data: order },
        zIndex: isSelected ? 1000 : (isPending ? 100 : 1),
      })

      // 点击事件
      marker.on('click', (e) => {
        e.domEvent.stopPropagation()
        this.selectOrder(order)
      })

      // 鼠标悬停
      marker.on('mouseover', () => {
        this.showOrderInfoWindow(order, marker)
      })

      marker.on('mouseout', () => {
        this.closeInfoWindow()
      })

      // 双击打开详情
      marker.on('dblclick', (e) => {
        e.domEvent.stopPropagation()
        this.orderDetail = order
        this.orderDetailVisible = true
      })

      return marker
    },

    createPersonMarker(person) {
      const isSelected = this.selectedPerson && this.selectedPerson.id === person.id
      const isIdle = person.status === 'idle'

      // 人员颜色：空闲=绿色，工作中=蓝色，离线=灰色
      const colorMap = {
        idle: '#67c23a',
        working: '#409eff',
        offline: '#909399',
      }
      const color = isSelected ? '#e6a23c' : colorMap[person.status] || '#909399'

      const marker = new AMap.Marker({
        position: person.position,
        title: person.name,
        content: this.createMarkerContent('person', color, isSelected, person.name),
        offset: new AMap.Pixel(0, -20),
        extData: { type: 'person', data: person },
        zIndex: isSelected ? 1000 : (isIdle ? 99 : 1),
      })

      // 点击事件
      marker.on('click', (e) => {
        e.domEvent.stopPropagation()
        if (person.status === 'offline') {
          this.$message.warning('该人员当前离线，无法派工')
          return
        }
        this.selectPerson(person)
      })

      // 鼠标悬停
      marker.on('mouseover', () => {
        this.showPersonInfoWindow(person, marker)
      })

      marker.on('mouseout', () => {
        this.closeInfoWindow()
      })

      // 双击打开详情
      marker.on('dblclick', (e) => {
        e.domEvent.stopPropagation()
        this.personDetail = person
        this.personDetailVisible = true
      })

      return marker
    },

    createMarkerContent(type, color, isSelected, label) {
      const size = isSelected ? 44 : 36
      const fontSize = isSelected ? 13 : 12
      return `<div style="
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
      ">
        <div style="
          width: ${size}px;
          height: ${size}px;
          border-radius: 50% ${size}px 0 ${size}px;
          background: ${color};
          border: 2px solid #fff;
          box-shadow: 0 2px 8px rgba(0,0,0,0.3);
          display: flex;
          align-items: center;
          justify-content: center;
          transform: rotate(-45deg);
          transition: all 0.2s;
        ">
          <i class="el-icon-${type === 'order' ? 'document' : 'user'}" style="
            transform: rotate(45deg);
            color: #fff;
            font-size: ${fontSize}px;
          "></i>
        </div>
        <span style="
          margin-top: 4px;
          padding: 2px 8px;
          background: ${color};
          color: #fff;
          font-size: 11px;
          border-radius: 3px;
          white-space: nowrap;
          box-shadow: 0 1px 4px rgba(0,0,0,0.2);
          max-width: 80px;
          overflow: hidden;
          text-overflow: ellipsis;
        ">${label}</span>
      </div>`
    },

    // ==========================================
    // 信息窗体
    // ==========================================

    showOrderInfoWindow(order, marker) {
      this.closeInfoWindow()
      const content = `
        <div style="padding: 8px; min-width: 180px;">
          <div style="font-weight: 600; font-size: 14px; margin-bottom: 6px; color: #303133;">${order.title}</div>
          <div style="font-size: 12px; color: #606266; margin-bottom: 4px;">
            <i class="el-icon-location" style="color: #909399;"></i> ${order.address || '--'}
          </div>
          <div style="display: flex; gap: 8px; align-items: center; font-size: 12px;">
            <span style="
              padding: 2px 6px;
              border-radius: 2px;
              background: ${
                order.status === 'pending' ? '#fef0f0' :
                order.status === 'dispatched' ? '#fdf6ec' :
                order.status === 'processing' ? '#ecf5ff' : '#f0f9ff'
              };
              color: ${
                order.status === 'pending' ? '#f56c6c' :
                order.status === 'dispatched' ? '#e6a23c' :
                order.status === 'processing' ? '#409eff' : '#67c23a'
              };
            ">${this.getStatusText(order.status)}</span>
            <span style="
              padding: 2px 6px;
              border-radius: 2px;
              background: ${
                order.priority === 'high' ? '#fef0f0' :
                order.priority === 'medium' ? '#fdf6ec' : '#f0f9ff'
              };
              color: ${
                order.priority === 'high' ? '#f56c6c' :
                order.priority === 'medium' ? '#e6a23c' : '#909399'
              };
            ">${this.getPriorityText(order.priority)}</span>
          </div>
          <div style="font-size: 11px; color: #909399; margin-top: 4px;">
            ${order.createTime} ${order.assignedName ? '· 已派给' + order.assignedName : '· 待派工'}
          </div>
          <div style="font-size: 11px; color: #409eff; margin-top: 4px; cursor: pointer;" onclick="window._mapViewDispatchOrder && window._mapViewDispatchOrder('${order.id}')">
            双击查看详情 →
          </div>
        </div>
      `
      const infoWindow = new AMap.InfoWindow({
        content,
        offset: new AMap.Pixel(0, -30),
        closeWhenClickMap: true,
      })
      infoWindow.open(this.map, marker.getPosition())
      this.currentInfoWindow = infoWindow
    },

    showPersonInfoWindow(person, marker) {
      this.closeInfoWindow()
      const content = `
        <div style="padding: 8px; min-width: 160px;">
          <div style="font-weight: 600; font-size: 14px; margin-bottom: 6px; color: #303133;">${person.name}
            <span style="
              font-size: 11px;
              padding: 2px 6px;
              border-radius: 2px;
              background: ${
                person.status === 'idle' ? '#f0f9ff' :
                person.status === 'working' ? '#ecf5ff' : '#f4f4f5'
              };
              color: ${
                person.status === 'idle' ? '#67c23a' :
                person.status === 'working' ? '#409eff' : '#909399'
              };
              margin-left: 6px;
            ">${this.getPersonStatusText(person.status)}</span>
          </div>
          ${person.phone ? `<div style="font-size: 12px; color: #606266; margin-bottom: 4px;">
            <i class="el-icon-phone" style="color: #909399;"></i> ${person.phone}
          </div>` : ''}
          ${person.address ? `<div style="font-size: 12px; color: #606266; margin-bottom: 4px;">
            <i class="el-icon-location" style="color: #909399;"></i> ${person.address}
          </div>` : ''}
          ${person.currentTask ? `<div style="font-size: 12px; color: #409eff; margin-bottom: 4px;">
            <i class="el-icon-edit" style="color: #409eff;"></i> 正在处理: ${person.currentTask}
          </div>` : ''}
          <div style="font-size: 11px; color: #909399;">
            今日已完成 ${person.completedToday || 0} 单
          </div>
        </div>
      `
      const infoWindow = new AMap.InfoWindow({
        content,
        offset: new AMap.Pixel(0, -30),
        closeWhenClickMap: true,
      })
      infoWindow.open(this.map, marker.getPosition())
      this.currentInfoWindow = infoWindow
    },

    closeInfoWindow() {
      if (this.currentInfoWindow) {
        this.currentInfoWindow.close()
        this.currentInfoWindow = null
      }
    },

    // ==========================================
    // 选择与路线
    // ==========================================

    selectOrder(order) {
      this.selectedOrder = order

      // 移动地图到工单位置
      if (this.map) {
        this.map.setCenter(order.position)
        this.map.setZoom(14)
      }

      // 清除路线
      this.clearRoute()

      // 计算每个人员到工单的距离
      this.updatePersonDistances(order)

      // 更新工单标记样式
      this.renderMarkers()

      this.closeInfoWindow()
    },

    selectPerson(person) {
      if (person.status === 'offline') {
        this.$message.warning('该人员当前离线，无法派工')
        return
      }
      this.selectedPerson = person

      // 清除路线
      this.clearRoute()

      // 更新人员标记样式
      this.renderMarkers()

      this.closeInfoWindow()
    },

    // 更新人员到工单的距离（使用 AMap 驾车路线）
    updatePersonDistances(targetOrder) {
      if (!this.map || !targetOrder.position) return

      this.personList.forEach(person => {
        if (!person.position || person.status === 'offline') return

        // 使用 AMap 驾车路线规划计算距离和时间
        this.driving.search(person.position, targetOrder.position, (status, result) => {
          if (status === 'complete' && result.routes && result.routes.length > 0) {
            const route = result.routes[0]
            // 距离（米）转公里
            const distanceKm = route.distance / 1000
            // 时间（秒）转分钟
            const etaMin = Math.ceil(route.time / 60)

            this.$set(person, 'distance', distanceKm)
            this.$set(person, 'eta', etaMin)
          } else {
            // 驾车路线规划失败，使用直线距离
            const dist = this.calculateLineDistance(person.position, targetOrder.position)
            this.$set(person, 'distance', dist)
            this.$set(person, 'eta', Math.round(dist * 3)) // 粗略估算：每公里3分钟
          }
        })
      })
    },

    // 计算直线距离（km）
    calculateLineDistance(p1, p2) {
      if (!p1 || !p2) return 0
      const R = 6371
      const lat1 = p1[1] * Math.PI / 180
      const lat2 = p2[1] * Math.PI / 180
      const deltaLat = (p2[1] - p1[1]) * Math.PI / 180
      const deltaLng = (p2[0] - p1[0]) * Math.PI / 180

      const a = Math.sin(deltaLat / 2) ** 2 +
        Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLng / 2) ** 2
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))

      return R * c
    },

    // 绘制路线
    drawRoute() {
      if (!this.selectedOrder || !this.selectedPerson) return
      if (!this.selectedOrder.position || !this.selectedPerson.position) {
        this.$message.warning('起点或终点坐标缺失，无法规划路线')
        return
      }

      this.clearRoute()

      this.driving.search(
        this.selectedPerson.position,
        this.selectedOrder.position,
        (status, result) => {
          if (status === 'complete' && result.routes && result.routes.length > 0) {
            this.routeOverlays = this.map.getAllOverlays('polyline')
            this.$message.success('路线已规划')
          } else {
            // 绘制简单的直线连接
            this.drawSimpleLine()
          }
        }
      )
    },

    // 绘制简单连接线
    drawSimpleLine() {
      const polyline = new AMap.Polyline({
        path: [this.selectedPerson.position, this.selectedOrder.position],
        strokeColor: '#67c23a',
        strokeOpacity: 0.8,
        strokeWeight: 3,
        strokeStyle: 'dashed',
        lineJoin: 'round',
      })
      this.map.add(polyline)
      this.routeOverlays.push(polyline)
      this.map.setFitView(polyline)
    },

    clearRoute() {
      if (this.map && this.driving) {
        this.driving.clear()
      }
      this.routeOverlays.forEach(overlay => {
        if (this.map) {
          this.map.remove(overlay)
        }
      })
      this.routeOverlays = []
    },

    clearAllOverlays() {
      this.orderMarkers.forEach(m => this.map && this.map.remove(m))
      this.personMarkers.forEach(m => this.map && this.map.remove(m))
      this.clearRoute()
      this.orderMarkers = []
      this.personMarkers = []
      this.closeInfoWindow()
    },

    // ==========================================
    // 派工操作
    // ==========================================

    handleDispatch() {
      if (!this.selectedOrder || !this.selectedPerson) {
        this.$message.warning('请选择工单和派工人员')
        return
      }

      if (this.selectedOrder.status !== 'pending') {
        this.$message.warning('该工单不是待派工状态')
        return
      }

      this.$confirm(`确认将工单"${this.selectedOrder.title}"派给"${this.selectedPerson.name}"吗？`, '确认派工', {
        confirmButtonText: '确认派工',
        cancelButtonText: '取消',
        type: 'info',
      }).then(() => {
        this.doDispatch()
      }).catch(() => {})
    },

    doDispatch() {
      this.dispatching = true
      const useMock = !this.isRealApiAvailable()

      if (useMock) {
        setTimeout(() => {
          this.dispatching = false
          // 更新本地状态
          const order = this.orderList.find(o => o.id === this.selectedOrder.id)
          if (order) {
            order.status = 'dispatched'
            order.assignedName = this.selectedPerson.name
          }
          // 更新人员状态
          const person = this.personList.find(p => p.id === this.selectedPerson.id)
          if (person) {
            person.status = 'working'
            person.currentTask = this.selectedOrder.title
          }
          this.dispatchSuccessVisible = true
        }, 500)
        return
      }

      this.$request({
        ...Api.DISPATCH,
        data: {
          orderId: this.selectedOrder.id,
          personId: this.selectedPerson.id,
        }
      }).asyncThen(() => {
        this.dispatching = false
        // 更新本地状态
        const order = this.orderList.find(o => o.id === this.selectedOrder.id)
        if (order) {
          order.status = 'dispatched'
          order.assignedName = this.selectedPerson.name
        }
        const person = this.personList.find(p => p.id === this.selectedPerson.id)
        if (person) {
          person.status = 'working'
          person.currentTask = this.selectedOrder.title
        }
        this.renderMarkers()
        this.dispatchSuccessVisible = true
      }).asyncErrorCatch(() => {
        this.dispatching = false
        this.$message.error('派工失败')
      })
    },

    handleDispatchSuccessConfirm() {
      this.dispatchSuccessVisible = false
      this.clearSelection()
    },

    handleDispatchFromDetail() {
      if (!this.orderDetail) return
      this.orderDetailVisible = false
      this.selectOrder(this.orderDetail)
    },

    // ==========================================
    // 面板滚动
    // ==========================================

    handleLeftPanelScroll() {
      // 可以在这里做虚拟滚动优化
    },

    // ==========================================
    // 自动刷新
    // ==========================================

    startAutoRefresh() {
      this.stopAutoRefresh()
      // 每60秒自动刷新一次人员位置
      this.refreshTimer = setInterval(() => {
        this.loadPersons()
      }, 60000)
    },

    stopAutoRefresh() {
      if (this.refreshTimer) {
        clearInterval(this.refreshTimer)
        this.refreshTimer = null
      }
    },

    // ==========================================
    // 查询与清空
    // ==========================================

    handleQuery() {
      this.clearSelection()
      this.loadData()
    },

    clearSelection() {
      this.selectedOrder = null
      this.selectedPerson = null
      this.clearRoute()
      this.renderMarkers()
    },

    // ==========================================
    // 地图操作
    // ==========================================

    zoomIn() {
      if (this.map) this.map.zoomIn()
    },

    zoomOut() {
      if (this.map) this.map.zoomOut()
    },

    toggleFullscreen() {
      const container = document.getElementById('map-container')
      if (!document.fullscreenElement) {
        container.requestFullscreen().catch(() => {})
      } else {
        document.exitFullscreen().catch(() => {})
      }
    },

    // ==========================================
    // 状态文本
    // ==========================================

    getStatusText(status) {
      const map = {
        pending: '待派工',
        dispatched: '已派工',
        processing: '处理中',
        completed: '已完成',
      }
      return map[status] || status
    },

    getPersonStatusText(status) {
      const map = {
        idle: '空闲',
        working: '工作中',
        offline: '离线',
      }
      return map[status] || status
    },

    getPriorityText(priority) {
      const map = {
        high: '紧急',
        medium: '一般',
        low: '低',
      }
      return map[priority] || priority
    },
  },
}

// 全局暴露，用于信息窗体中的双击事件
if (typeof window !== 'undefined') {
  window._mapViewDispatchOrder = function(orderId) {
    // 在实例中找到对应的工单并打开详情
    const vm = window._mapViewInstance
    if (vm && orderId) {
      const order = vm.orderList.find(o => o.id === orderId)
      if (order) {
        vm.orderDetail = order
        vm.orderDetailVisible = true
      }
    }
  }
}
</script>

<style lang="scss" scoped>
.apaas-custom-map-view {
  height: 100%;
  width: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f5f7fa;

  // ==========================================
  // 顶部工具栏
  // ==========================================
  .toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 16px;
    background: #fff;
    border-bottom: 1px solid #e4e7ed;
    flex-shrink: 0;

    .toolbar-left {
      display: flex;
      align-items: center;
      gap: 12px;

      .page-title {
        font-size: 16px;
        font-weight: 600;
        color: #303133;
      }

      .stat-badge {
        display: flex;
        align-items: center;
        gap: 5px;
        font-size: 12px;
        color: #606266;
        background: #f4f4f5;
        padding: 2px 10px;
        border-radius: 12px;

        .stat-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;

          &--pending { background: #f56c6c; }
          &--processing { background: #409eff; }
        }
      }
    }

    .toolbar-right {
      display: flex;
      align-items: center;
      gap: 8px;
    }
  }

  // ==========================================
  // 主体内容区
  // ==========================================
  .main-content {
    flex: 1;
    display: flex;
    min-height: 0;
    gap: 1px;
    background: #e4e7ed;
  }

  // ==========================================
  // 左右面板
  // ==========================================
  .left-panel,
  .right-panel {
    width: 300px;
    background: #fff;
    display: flex;
    flex-direction: column;
    flex-shrink: 0;

    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 14px;
      border-bottom: 1px solid #e4e7ed;
      flex-shrink: 0;

      .panel-title {
        font-weight: 600;
        font-size: 14px;
        color: #303133;
      }

      .panel-count {
        font-size: 12px;
        color: #909399;
        background: #f4f4f5;
        padding: 1px 8px;
        border-radius: 10px;
      }
    }

    .panel-body {
      flex: 1;
      overflow-y: auto;
      padding: 8px;

      // 滚动条美化
      &::-webkit-scrollbar {
        width: 4px;
      }
      &::-webkit-scrollbar-thumb {
        background: #c0c4cc;
        border-radius: 2px;
      }
    }
  }

  // ==========================================
  // 工单项
  // ==========================================
  .order-item {
    padding: 10px 12px;
    margin-bottom: 6px;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;

    &:hover {
      border-color: #c0d4ff;
      background: #f5f9ff;
    }

    &.is-selected {
      border-color: #409eff;
      background: #ecf5ff;
      box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
    }

    .order-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;

      .order-name {
        font-weight: 600;
        font-size: 13px;
        color: #303133;
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        margin-right: 6px;
      }

      .order-status {
        font-size: 11px;
        padding: 2px 6px;
        border-radius: 3px;
        flex-shrink: 0;

        &.status-pending { background: #fef0f0; color: #f56c6c; }
        &.status-dispatched { background: #fdf6ec; color: #e6a23c; }
        &.status-processing { background: #ecf5ff; color: #409eff; }
        &.status-completed { background: #f0f9ff; color: #67c23a; }
      }
    }

    .order-info {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 4px;

      .order-address {
        color: #606266;
        font-size: 11px;
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;

        i { margin-right: 3px; color: #909399; }
      }

      .order-priority {
        font-size: 11px;
        padding: 1px 5px;
        border-radius: 2px;
        flex-shrink: 0;
        margin-left: 6px;

        &.priority-high { background: #fef0f0; color: #f56c6c; }
        &.priority-medium { background: #fdf6ec; color: #e6a23c; }
        &.priority-low { background: #f0f9ff; color: #909399; }
      }
    }

    .order-meta {
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      color: #909399;

      .order-assignee {
        i { margin-right: 2px; }
      }
    }
  }

  // ==========================================
  // 人员项
  // ==========================================
  .person-item {
    display: flex;
    align-items: flex-start;
    padding: 10px 12px;
    margin-bottom: 6px;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;

    &:hover {
      border-color: #c0d4ff;
      background: #f5f9ff;
    }

    &.is-selected {
      border-color: #409eff;
      background: #ecf5ff;
      box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
    }

    &.is-offline {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .person-avatar {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      margin-right: 10px;
      flex-shrink: 0;

      &.avatar--idle { background: #67c23a; }
      &.avatar--working { background: #409eff; }
      &.avatar--offline { background: #909399; }
    }

    .person-info {
      flex: 1;
      min-width: 0;

      .person-name {
        font-weight: 600;
        font-size: 13px;
        color: #303133;
        margin-bottom: 3px;
        display: flex;
        align-items: center;
        gap: 6px;

        .person-phone {
          font-size: 10px;
          color: #909399;
          font-weight: normal;
        }
      }

      .person-meta {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        margin-bottom: 3px;

        .person-status {
          padding: 1px 5px;
          border-radius: 2px;

          &.status-idle { background: #f0f9ff; color: #67c23a; }
          &.status-working { background: #ecf5ff; color: #409eff; }
          &.status-offline { background: #f4f4f5; color: #909399; }
        }

        .person-task {
          color: #606266;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          max-width: 120px;
        }
      }

      .person-distance {
        font-size: 11px;
        color: #409eff;

        i { margin-right: 3px; }

        .person-eta {
          color: #909399;
          margin-left: 4px;
        }
      }
    }
  }

  // ==========================================
  // 空/加载状态
  // ==========================================
  .empty-state,
  .loading-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 40px 0;
    color: #909399;

    i {
      font-size: 40px;
      margin-bottom: 10px;
    }

    span { font-size: 13px; }
  }

  // ==========================================
  // 地图容器
  // ==========================================
  .map-container {
    flex: 1;
    position: relative;
    background: #fff;

    .amap {
      width: 100%;
      height: 100%;

      // 高德地图 logo 移到左下
      :deep(.amap-logo) {
        left: 10px;
        bottom: 5px;
      }
      // 版权信息
      :deep(.amap-copyright) {
        display: none;
      }
    }

    // 加载遮罩
    .map-loading-mask {
      position: absolute;
      inset: 0;
      background: rgba(255, 255, 255, 0.9);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      z-index: 100;

      .map-loading-icon {
        font-size: 32px;
        color: #409eff;
        margin-bottom: 8px;
      }

      span {
        font-size: 13px;
        color: #606266;
      }
    }

    // 图例
    .map-legend {
      position: absolute;
      top: 12px;
      left: 12px;
      background: rgba(255, 255, 255, 0.95);
      backdrop-filter: blur(4px);
      padding: 10px 14px;
      border-radius: 6px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
      z-index: 10;

      .legend-item {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        color: #606266;
        margin-bottom: 5px;

        &:last-child { margin-bottom: 0; }

        .legend-marker {
          width: 10px;
          height: 10px;
          border-radius: 2px;

          &--order { background: #f56c6c; }
          &--person { background: #409eff; }
          &--selected { background: #67c23a; }
        }
      }
    }

    // 地图操作按钮
    .map-actions {
      position: absolute;
      top: 12px;
      right: 12px;
      z-index: 10;
    }
  }

  // ==========================================
  // 底部派工栏
  // ==========================================
  .dispatch-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 16px;
    background: #fff;
    border-top: 1px solid #e4e7ed;
    flex-shrink: 0;

    .dispatch-info {
      flex: 1;

      .dispatch-tip {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        margin-right: 20px;
        color: #606266;
        font-size: 13px;

        i { color: #909399; }

        strong { color: #303133; }

        .tip-distance {
          color: #909399;
          font-size: 12px;
        }

        &--order i { color: #f56c6c; }
        &--person i { color: #409eff; }
      }

      .dispatch-hint {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        color: #909399;
        font-size: 12px;

        i { color: #909399; }
      }
    }

    .dispatch-actions {
      display: flex;
      gap: 8px;
    }
  }

  // ==========================================
  // 派工成功弹窗
  // ==========================================
  .dispatch-result {
    text-align: center;
    padding: 10px 0;

    .dispatch-icon {
      font-size: 56px;
      color: #67c23a;
      margin-bottom: 12px;
    }

    p {
      margin: 6px 0;
      color: #303133;
      font-size: 15px;

      strong { color: #409eff; }
    }

    .dispatch-detail {
      font-size: 13px !important;
      color: #909399 !important;
    }

    .dispatch-order-info {
      margin-top: 16px;
      padding: 12px;
      background: #f5f7fa;
      border-radius: 6px;
      text-align: left;

      .dispatch-info-item {
        display: flex;
        gap: 10px;
        font-size: 13px;
        margin-bottom: 6px;

        &:last-child { margin-bottom: 0; }

        .info-label {
          color: #909399;
          flex-shrink: 0;
        }

        .info-value {
          color: #303133;
          word-break: break-all;
        }
      }
    }
  }

  // ==========================================
  // 详情弹窗
  // ==========================================
  .person-detail,
  .order-detail {
    .detail-row {
      display: flex;
      gap: 12px;
      padding: 8px 0;
      border-bottom: 1px solid #f0f0f0;
      font-size: 13px;

      &:last-child { border-bottom: none; }

      &--block {
        flex-direction: column;
        gap: 4px;
      }

      .detail-label {
        color: #909399;
        flex-shrink: 0;
        width: 70px;
      }

      .detail-value {
        color: #303133;
        flex: 1;

        a { color: #409eff; text-decoration: none; }
        a:hover { text-decoration: underline; }

        .text-muted { color: #c0c4cc; }

        .person-status,
        .order-status,
        .order-priority {
          font-size: 12px;
          padding: 2px 6px;
          border-radius: 3px;
        }
      }
    }
  }

  // ==========================================
  // 过渡动画
  // ==========================================
  .fade-tip-enter-active,
  .fade-tip-leave-active {
    transition: all 0.3s;
  }
  .fade-tip-enter {
    opacity: 0;
    transform: translateY(5px);
  }
  .fade-tip-leave-to {
    opacity: 0;
    transform: translateY(-5px);
  }
}
</style>

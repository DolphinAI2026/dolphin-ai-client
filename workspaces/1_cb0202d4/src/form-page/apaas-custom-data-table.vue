<template>
  <div class="apaas-custom-data-table">

    <!-- 筛选区 -->
    <div class="filter-area">
      <el-input
        v-model="filterForm.keyword"
        placeholder="请输入关键词"
        size="small"
        clearable
        style="width: 220px"
      />
    </div>

    <!-- 查询 / 重置 -->
    <div class="filter-actions">
      <el-button type="primary" size="small" @click="handleQuery">查询</el-button>
      <el-button size="small" @click="handleReset">重置</el-button>
    </div>

    <!-- 已选提示条（弹窗选择场景需要） -->
    <div class="selected-bar">
      <span class="selected-bar-title">
        已选数据
        <span v-if="selectedRows.length" class="selected-badge">{{ selectedRows.length }}</span>
      </span>
      <template v-if="selectedRows.length === 0">
        <span class="selected-bar-empty">暂未选择</span>
      </template>
      <template v-else>
        <div class="selected-bar-tags">
          <span v-for="row in selectedRows" :key="row.id" class="bar-tag">
            <span class="bar-tag-label">{{ row.name || row.id }}</span>
            <span class="bar-tag-close" @click="removeSelected(row)">&times;</span>
          </span>
        </div>
        <span class="bar-clear" @click="clearAllSelected">清空</span>
      </template>
    </div>

    <!-- 数据表格 -->
    <div class="table-wrapper" style="overflow-y:auto; flex:1; min-height:0;">
      <el-table
        ref="elTable"
        :data="tableConfig.tableData || []"
        border
        style="width:100%;"
        :max-height="tableConfig.maxHeight || undefined"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="50" fixed />
        <el-table-column type="index" label="序" width="50" fixed :index="indexStart" />
        <el-table-column
          v-for="col in visibleCols"
          :key="col.columnKey"
          :prop="col.prop"
          :label="col.label"
          :min-width="col.minWidth || 120"
          show-overflow-tooltip
        />
      </el-table>
      <el-pagination
        v-if="tableConfig.pagination"
        style="margin-top: 8px; text-align: right; padding: 4px 0"
        :current-page="tableConfig.pagination.currentPage"
        :page-size="tableConfig.pagination.pageSize"
        :total="tableConfig.pagination.total"
        :page-sizes="[10, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @size-change="onSizeChange"
        @current-change="onCurrentPageChange"
      />
    </div>

  </div>
</template>

<script>
import Api from "../api";

export default {
  name: "apaas-custom-data-table",

  data() {
    return {
      filterForm: {
        keyword: "",
      },
      selectedRows: [],

      tableConfig: {
        maxHeight: "500",
        colConfigs: [
          { prop: "name", columnKey: "name", displayFlag: true, label: "名称", minWidth: 150 },
          { prop: "code", columnKey: "code", displayFlag: true, label: "编码", minWidth: 150 },
          { prop: "status", columnKey: "status", displayFlag: true, label: "状态", minWidth: 100 },
        ],
        tableData: [],
        pagination: {
          currentPage: 1,
          pageSize: 10,
          total: 0,
        },
      },
    };
  },

  computed: {
    visibleCols() {
      return (this.tableConfig.colConfigs || []).filter((c) => c.displayFlag);
    },
    indexStart() {
      const p = this.tableConfig.pagination;
      if (!p) return 1;
      return (p.currentPage - 1) * p.pageSize + 1;
    },
  },

  created() {
    this.loadTableData();
  },

  methods: {
    loadTableData() {
      const { currentPage, pageSize } = this.tableConfig.pagination;
      this.$request({
        ...Api.QUERY_LIST,
        params: {
          page: currentPage,
          pageSize,
          keyword: this.filterForm.keyword,
        },
      })
        .asyncThen((resp) => {
          const list = resp && resp.data ? resp.data : [];
          const total = resp && resp.total ? resp.total : 0;
          this.$set(this.tableConfig, "tableData", list);
          this.$set(this.tableConfig.pagination, "total", total);
          const selectedIds = this.selectedRows.map((r) => r.id);
          if (selectedIds.length) {
            this.reapplySelection(selectedIds);
          }
        })
        .asyncErrorCatch((error) => {
          console.error("加载数据失败:", error);
        });
    },

    handleQuery() {
      this.$set(this.tableConfig.pagination, "currentPage", 1);
      this.loadTableData();
    },

    handleReset() {
      this.filterForm.keyword = "";
      this.$set(this.tableConfig.pagination, "currentPage", 1);
      this.loadTableData();
    },

    onSizeChange(size) {
      this.$set(this.tableConfig.pagination, "pageSize", size);
      this.$set(this.tableConfig.pagination, "currentPage", 1);
      this.loadTableData();
    },

    onCurrentPageChange(page) {
      this.$set(this.tableConfig.pagination, "currentPage", page);
      this.loadTableData();
    },

    handleSelectionChange(rows) {
      const currentPageIds = new Set(
        (this.tableConfig.tableData || []).map((r) => r.id)
      );
      const otherPageRows = this.selectedRows.filter(
        (r) => !currentPageIds.has(r.id)
      );
      this.selectedRows = [
        ...otherPageRows,
        ...(Array.isArray(rows) ? rows : []),
      ];
    },

    reapplySelection(selectedIds) {
      this.$nextTick(() => {
        const table = this.$refs.elTable;
        if (!table) return;
        table.clearSelection();
        (this.tableConfig.tableData || []).forEach((row) => {
          if (selectedIds.includes(row.id)) {
            table.toggleRowSelection(row, true);
          }
        });
      });
    },

    removeSelected(row) {
      this.selectedRows = this.selectedRows.filter((r) => r.id !== row.id);
      const table = this.$refs.elTable;
      const tableData = this.tableConfig.tableData || [];
      const found = tableData.find((r) => r.id === row.id);
      if (found && table) {
        table.toggleRowSelection(found, false);
      }
    },

    clearAllSelected() {
      this.selectedRows = [];
      const table = this.$refs.elTable;
      if (table) table.clearSelection();
    },

    /**
     * 供弹窗"确定"按钮调用，返回当前所有已选行数据
     */
    getSelectedData() {
      return this.selectedRows;
    },
  },
};
</script>

<style lang="scss">
.apaas-custom-data-table {
  height: 100%;
  width: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 16px;
  overflow: hidden;

  .filter-area {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
    flex-wrap: wrap;
  }

  .filter-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    flex-shrink: 0;
  }

  .selected-bar {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    flex-shrink: 0;
    padding: 6px 10px;
    background: #f0f7ff;
    border: 1px solid #b3d8ff;
    border-radius: 4px;
    font-size: 13px;
    min-height: 36px;
    max-height: 72px;
    overflow-y: auto;

    .selected-bar-title {
      font-weight: 600;
      color: #303133;
      white-space: nowrap;
      flex-shrink: 0;

      .selected-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 18px;
        height: 18px;
        padding: 0 5px;
        background: #409eff;
        color: #fff;
        border-radius: 9px;
        font-size: 11px;
        font-weight: 600;
        margin-left: 4px;
      }
    }

    .selected-bar-empty { color: #c0c4cc; font-style: italic; }

    .selected-bar-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      flex: 1;

      .bar-tag {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        height: 22px;
        padding: 0 6px;
        background: #fff;
        border: 1px solid #b3d8ff;
        border-radius: 3px;
        font-size: 12px;
        color: #409eff;

        .bar-tag-label { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .bar-tag-close { cursor: pointer; color: #909399; &:hover { color: #f56c6c; } }
      }
    }

    .bar-clear {
      margin-left: auto;
      color: #909399;
      cursor: pointer;
      font-size: 12px;
      white-space: nowrap;
      flex-shrink: 0;
      &:hover { color: #f56c6c; }
    }
  }
}

.x-lov-modal {
  .apaas-custom-data-table {
    // 弹窗内高度有限，按需压缩各区域
  }
}
</style>

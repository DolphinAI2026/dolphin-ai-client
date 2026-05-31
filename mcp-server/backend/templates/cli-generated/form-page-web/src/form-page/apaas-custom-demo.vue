<template>
  <div class="apaas-custom-demo">
    <x-ag-grid
      rowKey="id"
      :tableData="tableData"
      :colConfigs="colConfigs"
      :pagination="pagination"
      @size-change="onSizeChange"
      @current-page-change="onCurrentPageChange"
    ></x-ag-grid>
  </div>
</template>

<script>
import Api from "../api";
export default {
  data() {
    return {
      tableData: [],
      colConfigs: [
        {
          headerName: "账号",
          field: "account",
        },
        {
          headerName: "工号",
          field: "userNumber",
        },
        {
          headerName: "用户名",
          field: "username",
        },
        {
          headerName: "部门名称",
          field: "deptName",
          showOverflowTooltip: true,
        },
        {
          headerName: "主部门",
          colId: "mainDepartment",
          valueGetter: (params) => params.data.mainDepartment?.name,
          flex: 1,
        },
      ],
      pagination: {
        currentPage: 1,
        pageSize: 10,
        total: 0,
      },
    };
  },
  created() {
    this.getTableData();
  },
  methods: {
    onSizeChange(size) {
      this.pagination.pageSize = size;
      this.getTableData();
    },
    onCurrentPageChange(page) {
      this.pagination.currentPage = page;
      this.getTableData();
    },
    getTableData() {
      const { currentPage, pageSize } = this.pagination;
      this.$request({
        ...Api.QUERY_ALL_USERS,
        params: {
          page: currentPage,
          pageSize,
        },
      })
        .asyncThen(
          (resp) => {
            this.tableData = resp.table;
            this.pagination.total = resp.total;
          },
          (error) => {
            console.error(error);
          }
        )
        .asyncErrorCatch((error) => {
          console.error(error);
        });
    },
  },
};
</script>

<style lang="scss">
.apaas-custom-demo {
  box-sizing: border-box;
  padding: 20px;
}
</style>

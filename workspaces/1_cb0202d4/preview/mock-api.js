/**
 * 模拟平台 $request：支持 mock 数据返回
 * 支持 .asyncThen().asyncErrorCatch() 链式调用（与平台行为一致）
 */

// Mock 数据
const mockData = {
  data: [
    { id: 1, name: '张三', code: 'EMP001', status: '在职' },
    { id: 2, name: '李四', code: 'EMP002', status: '在职' },
    { id: 3, name: '王五', code: 'EMP003', status: '离职' },
    { id: 4, name: '赵六', code: 'EMP004', status: '在职' },
    { id: 5, name: '钱七', code: 'EMP005', status: '在职' },
    { id: 6, name: '孙八', code: 'EMP006', status: '离职' },
    { id: 7, name: '周九', code: 'EMP007', status: '在职' },
    { id: 8, name: '吴十', code: 'EMP008', status: '在职' },
    { id: 9, name: '郑十一', code: 'EMP009', status: '离职' },
    { id: 10, name: '陈十二', code: 'EMP010', status: '在职' },
    { id: 11, name: '刘十三', code: 'EMP011', status: '在职' },
    { id: 12, name: '杨十四', code: 'EMP012', status: '离职' },
    { id: 13, name: '黄十五', code: 'EMP013', status: '在职' },
    { id: 14, name: '林十六', code: 'EMP014', status: '在职' },
    { id: 15, name: '徐十七', code: 'EMP015', status: '离职' },
    { id: 16, name: '何十八', code: 'EMP016', status: '在职' },
    { id: 17, name: '高十九', code: 'EMP017', status: '在职' },
    { id: 18, name: '罗二十', code: 'EMP018', status: '离职' },
    { id: 19, name: '郭二十一', code: 'EMP019', status: '在职' },
    { id: 20, name: '宋二十二', code: 'EMP020', status: '在职' },
  ],
  total: 20,
};

export function installMockRequest(Vue) {
  Vue.prototype.$request = function (config) {
    const ctrl = {};

    // 生成 mock 响应
    const mockResponse = (params) => {
      let data = [...mockData.data];
      let total = mockData.total;

      // 模拟关键词搜索过滤
      if (params && params.keyword) {
        const keyword = params.keyword.toLowerCase();
        data = data.filter(
          (item) =>
            item.name.toLowerCase().includes(keyword) ||
            item.code.toLowerCase().includes(keyword)
        );
        total = data.length;
      }

      // 模拟分页
      const page = params && params.page ? params.page : 1;
      const pageSize = params && params.pageSize ? params.pageSize : 10;
      const start = (page - 1) * pageSize;
      const end = start + pageSize;
      data = data.slice(start, end);

      return {
        data,
        total,
        page,
        pageSize,
      };
    };

    // 使用 Promise 模拟异步请求
    const promise = new Promise((resolve) => {
      setTimeout(() => {
        const response = mockResponse(config.params);
        resolve(response);
      }, 300); // 模拟 300ms 网络延迟
    });

    ctrl.asyncThen = function (onSuccess, onError) {
      promise.then(onSuccess).catch(onError || function () {});
      return ctrl;
    };

    ctrl.asyncErrorCatch = function (onError) {
      promise.catch(onError);
      return ctrl;
    };

    return ctrl;
  };
}

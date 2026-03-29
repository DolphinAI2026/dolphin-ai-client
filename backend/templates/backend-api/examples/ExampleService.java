package {basePackage}.service;

import com.definesys.mpaas.common.http.Response;
import {basePackage}.dto.ExampleCreateRequest;
import {basePackage}.dto.ExampleQueryRequest;
import {basePackage}.dto.PageRequest;

/**
 * 示例服务接口
 *
 * 规范要点：
 * 1. 接口放在 {basePackage}.service 包下
 * 2. 命名规则：大驼峰 + Service
 * 3. 方法使用 Javadoc 注释说明功能、参数、返回值
 */
public interface ExampleService {

    /**
     * 分页查询
     *
     * @param request 分页查询请求
     * @return 分页结果
     */
    Response pageQuery(PageRequest<ExampleQueryRequest> request);

    /**
     * 根据ID查询详情
     *
     * @param id 主键ID
     * @return 详情数据
     */
    Response getDetail(String id);

    /**
     * 新增
     *
     * @param request 创建请求
     * @return 操作结果
     */
    Response create(ExampleCreateRequest request);

    /**
     * 更新
     *
     * @param request 更新请求
     * @return 操作结果
     */
    Response update(ExampleCreateRequest request);

    /**
     * 删除
     *
     * @param id 主键ID
     * @return 操作结果
     */
    Response delete(String id);
}

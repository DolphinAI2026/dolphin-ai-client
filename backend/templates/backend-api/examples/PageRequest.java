package {basePackage}.dto;

import lombok.Data;

/**
 * 通用分页请求
 *
 * 规范要点：
 * 1. 使用泛型 T 支持不同的查询条件
 * 2. 限制最大分页大小，防止大数据量查询
 * 3. 配合各模块的 QueryRequest 使用
 *
 * 使用示例：
 *   PageRequest<UserQueryRequest> request = new PageRequest<>();
 *   request.setPage(1);
 *   request.setPageSize(20);
 *   request.setCondition(queryCondition);
 */
@Data
public class PageRequest<T> {

    private static final int MAX_PAGE_SIZE = 2000;

    /**
     * 每页大小
     */
    private int pageSize;

    /**
     * 当前页码
     */
    private int page;

    /**
     * 升序排序字段
     */
    private String[] ascs;

    /**
     * 降序排序字段
     */
    private String[] descs;

    /**
     * 查询条件
     */
    private T condition;

    public int getPageSize() {
        if (pageSize > MAX_PAGE_SIZE) {
            return MAX_PAGE_SIZE;
        }
        return pageSize;
    }
}

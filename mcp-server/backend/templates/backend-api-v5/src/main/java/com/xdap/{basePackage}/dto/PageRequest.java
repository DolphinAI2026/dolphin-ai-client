package com.xdap.{basePackage}.dto;

import lombok.Data;

/**
 * 通用分页请求
 *
 * @param <T> 查询条件类型
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

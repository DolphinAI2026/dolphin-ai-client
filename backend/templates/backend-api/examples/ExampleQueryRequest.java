package {basePackage}.dto;

import lombok.Data;

import java.util.Date;

/**
 * 示例 - 查询条件 DTO
 *
 * 规范要点：
 * 1. 查询条件单独封装为 DTO
 * 2. 配合 PageRequest<T> 使用，作为泛型参数传入
 */
@Data
public class ExampleQueryRequest {

    /**
     * 名称（模糊查询）
     */
    private String name;

    /**
     * 状态
     */
    private String status;

    /**
     * 类型
     */
    private String type;

    /**
     * 查询起始日期
     */
    private Date dateBegin;

    /**
     * 查询结束日期
     */
    private Date dateEnd;
}

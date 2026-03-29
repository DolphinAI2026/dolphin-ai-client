package {basePackage}.dto;

import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * 示例 - 创建/更新请求 DTO
 *
 * 规范要点：
 * 1. 放在 {basePackage}.dto 包下
 * 2. 使用 @Data 注解
 * 3. 命名规则：大驼峰 + 语义后缀（如 Request、DTO）
 * 4. 必填字段使用 @NotNull 或 @NotBlank 校验注解
 * 5. Controller 中使用 @Validated 触发校验
 * 6. 禁止直接将 Pojo 实体类作为 Controller 的入参
 */
@Data
public class ExampleCreateRequest {

    /**
     * 主键ID（更新时使用）
     */
    private String id;

    /**
     * 名称（必填）
     */
    @NotBlank(message = "名称不能为空")
    private String name;

    /**
     * 类型（必填）
     */
    @NotNull(message = "类型不能为空")
    private String type;

    /**
     * 描述（选填）
     */
    private String description;
}

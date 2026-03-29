package {basePackage}.enums;

/**
 * 示例通用枚举
 *
 * 规范要点：
 * 1. 放在 {basePackage}.enums 包下
 * 2. 命名规则：大驼峰 + Enum
 * 3. 标准结构：code + value 双字段，提供 getter 方法
 * 4. 用于业务状态、类型等常量定义，避免魔法字符串
 * 5. 当枚举值需要存入数据库时（数据库以 ["value"] 格式存储），
 *    需提供 getBCode() 方法返回带中括号格式
 */
public enum ExampleStatusEnum {

    ACTIVE("ACTIVE", "启用"),
    INACTIVE("INACTIVE", "停用"),
    PENDING("PENDING", "待审核");

    private String code;
    private String value;

    ExampleStatusEnum(String code, String value) {
        this.code = code;
        this.value = value;
    }

    public String getCode() {
        return code;
    }

    public String getValue() {
        return value;
    }

    /**
     * 获取数据库存储格式的 code
     * 数据库中部分字段以 ["value"] 格式存储，查询时需使用此方法
     *
     * 示例：ACTIVE.getBCode() → ["ACTIVE"]
     *
     * 使用场景：
     *   mpaasQuery.eq("status", ExampleStatusEnum.ACTIVE.getBCode())
     */
    public String getBCode() {
        return "[\"" + code + "\"]";
    }
}

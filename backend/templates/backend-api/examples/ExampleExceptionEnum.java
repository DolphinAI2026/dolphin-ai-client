package {basePackage}.enums;

import com.xdap.motor.exception.BaseExceptionEnumInterface;

/**
 * 示例模块异常枚举
 *
 * 规范要点：
 * 1. 放在 {basePackage}.enums 包下
 * 2. 必须实现 BaseExceptionEnumInterface 接口
 * 3. 错误码格式：模块前缀-编号，例如 EXAMPLE-001
 * 4. message 中支持 {0}、{1} 等占位符，用于动态参数
 * 5. 配合 XDapBizException 使用：throw new XDapBizException(ExampleExceptionEnum.EXAMPLE_NOT_EXISTS, id)
 */
public enum ExampleExceptionEnum implements BaseExceptionEnumInterface {

    EXAMPLE_NOT_EXISTS("EXAMPLE-001", "EXAMPLE({0})_NOT_EXISTS"),
    EXAMPLE_ALREADY_EXISTS("EXAMPLE-002", "EXAMPLE({0})_ALREADY_EXISTS"),
    PARAM_ERROR("EXAMPLE-003", "PARAM_ERROR");

    private String code;
    private String message;

    ExampleExceptionEnum(String code, String message) {
        this.code = code;
        this.message = message;
    }

    @Override
    public String getCode() {
        return this.code;
    }

    @Override
    public String getMessage() {
        return this.message;
    }
}

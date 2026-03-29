package {basePackage}.dao;

import com.definesys.mpaas.query.MpaasQuery;
import {basePackage}.config.DatasourceUtil;
import com.xdap.common.domain.constant.DocumentNumConstant;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

/**
 * 流水码生成示例
 *
 * 流水码（WaterCode）用于生成业务单据的唯一编号，如工单号、订单号等。
 * 通过调用数据库存储过程实现递增序号，支持不同的重置策略。
 *
 * 前置条件：
 * 1. 数据库中需要存在对应的存储过程（由平台提供）
 * 2. 需要在平台中配置流水码规则，获取 waterRuleId 和 componentId
 * 3. 在 application.properties 中配置对应的 ID
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class ExampleWaterCode {

    private final DatasourceUtil datasourceUtil;

    /**
     * 流水码规则ID（在平台中配置后获取）
     */
    @Value("${example.waterCode.waterRuleId:}")
    private String waterRuleId;

    /**
     * 流水码组件ID（在平台中配置后获取）
     */
    @Value("${example.waterCode.componentId:}")
    private String componentId;

    // ==================== 核心方法：调用存储过程生成流水码 ====================

    /**
     * 调用数据库存储过程生成流水码
     *
     * @param waterRuleId 流水码规则ID（平台配置）
     * @param componentId 流水码组件ID（平台配置）
     * @param resetType   重置类型，取值：
     *                    - DocumentNumConstant.EVERY_DAY   每日重置
     *                    - DocumentNumConstant.EVERY_MONTH  每月重置
     *                    - DocumentNumConstant.EVERY_YEAR   每年重置
     *                    - DocumentNumConstant.NEVER        永不重置
     * @return 递增的序号（整数）
     */
    public int callWaterCodeProcedure(String waterRuleId, String componentId, String resetType) {
        // 根据重置类型选择不同的存储过程
        // water_code_procedure_daily   — 每日重置
        // water_code_procedure_monthly — 每月重置
        // water_code_procedure_yearly  — 每年重置
        // water_code_procedure_never   — 永不重置
        String procedureName = "water_code_procedure_" + resetType;

        MpaasQuery mpaasQuery = datasourceUtil.buildDefaultMpaasQuery();
        // 存储过程接收 2 个输入参数 + 1 个输出参数（返回递增序号）
        int waterCode = mpaasQuery.callProcedure(procedureName, waterRuleId, componentId);
        return waterCode;
    }

    // ==================== 使用示例：生成各种格式的业务编号 ====================

    /**
     * 示例1：生成工单编号
     * 格式：W + 年月日 + 4位流水码，例如 W20250323-0001
     * 重置类型：每日重置
     */
    public String generateCaseNumber() {
        int waterCode = callWaterCodeProcedure(waterRuleId, componentId, DocumentNumConstant.EVERY_DAY);
        String dateStr = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        return "W" + dateStr + String.format("%04d", waterCode);
    }

    /**
     * 示例2：生成订单编号
     * 格式：8位流水码，例如 00000001
     * 重置类型：永不重置
     */
    public String generateOrderNumber() {
        int waterCode = callWaterCodeProcedure(waterRuleId, componentId, DocumentNumConstant.NEVER);
        return String.format("%08d", waterCode);
    }

    /**
     * 示例3：生成带前缀的编号
     * 格式：B + 年月日 + 4位流水码，例如 B20250323-0001
     * 重置类型：永不重置
     */
    public String generateBonusNumber() {
        int waterCode = callWaterCodeProcedure(waterRuleId, componentId, DocumentNumConstant.NEVER);
        String dateStr = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        return "B" + dateStr + String.format("%04d", waterCode);
    }

    // ==================== 配置说明 ====================

    /**
     * application.properties 配置示例：
     *
     * # 流水码配置（waterRuleId 和 componentId 需在平台中创建流水码规则后获取）
     * example.waterCode.waterRuleId=xxxxxxxxxxxxxxxxxxxxx
     * example.waterCode.componentId=xxxxxxxxxxxxxxxxxxxxx
     *
     * 使用步骤：
     * 1. 在平台管理后台创建流水码规则，配置重置策略
     * 2. 获取规则生成的 waterRuleId 和 componentId
     * 3. 将 ID 配置到 application.properties 中
     * 4. 在 Dao 层注入并调用 callWaterCodeProcedure 方法
     * 5. 根据业务需求格式化返回的序号
     */
}

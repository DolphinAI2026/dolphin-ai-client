package {basePackage}.pojo;

import com.definesys.mpaas.query.annotation.Column;
import com.definesys.mpaas.query.annotation.ColumnType;
import com.definesys.mpaas.query.annotation.Table;
import com.definesys.mpaas.query.json.MpaasDateTimeDeserializer;
import com.definesys.mpaas.query.json.MpaasDateTimeSerializer;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import lombok.Data;

import java.util.Date;

/**
 * 示例实体类
 *
 * 规范要点：
 * 1. 放在 {basePackage}.pojo 包下
 * 2. 使用 @Data 注解（Lombok）
 * 3. 使用 @Table("表名") 注解映射数据库表
 * 4. 继承 MainCommonPo 类
 * 5. 每个字段使用 @Column("db_column_name") 注解映射数据库字段
 * 6. 非数据库字段使用 @Column(type = ColumnType.JAVA) 标记
 * 7. Date 类型字段需要序列化时使用 @JsonSerialize / @JsonDeserialize
 */
@Data
@Table("t_example")
public class Example extends MainCommonPo {

    /**
     * 名称
     */
    @Column("name")
    private String name;

    /**
     * 类型
     */
    @Column("type")
    private String type;

    /**
     * 描述
     */
    @Column("description")
    private String description;

    /**
     * 是否启用
     */
    @Column("is_active")
    private String isActive;

    /**
     * 开始日期 — Date 类型字段需添加序列化/反序列化注解
     */
    @Column("start_date")
    @JsonSerialize(using = MpaasDateTimeSerializer.class)
    @JsonDeserialize(using = MpaasDateTimeDeserializer.class)
    private Date startDate;

    /**
     * 结束日期
     */
    @Column("end_date")
    @JsonSerialize(using = MpaasDateTimeSerializer.class)
    @JsonDeserialize(using = MpaasDateTimeDeserializer.class)
    private Date endDate;

    /**
     * 非数据库字段（仅 Java 层使用，不映射数据库列）
     * 使用 @Column(type = ColumnType.JAVA) 标记
     */
    @Column(type = ColumnType.JAVA)
    private Boolean isDefaultChoice;
}

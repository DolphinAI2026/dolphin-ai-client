package {basePackage}.vo;

import com.definesys.mpaas.query.annotation.Column;
import com.definesys.mpaas.query.annotation.SQL;
import com.definesys.mpaas.query.annotation.SQLQuery;
import lombok.Data;

import java.util.Date;

/**
 * 示例视图对象（VO）
 *
 * 规范要点：
 * 1. 放在 {basePackage}.vo 包下
 * 2. 使用 @Data 注解
 * 3. VO 用于封装返回给前端的数据，可以组合多个表的字段
 * 4. 可配合 @SQLQuery + @SQL 定义数据库视图查询
 * 5. 命名规则：大驼峰 + VO
 */
@Data
@SQLQuery(
        @SQL(view = "exampleView",
             sql = "SELECT a.id, a.name, a.type, a.status, b.category_name "
                 + "FROM t_example a "
                 + "LEFT JOIN t_category b ON a.category_id = b.id")
)
public class ExampleVO {

    @Column("id")
    private String id;

    @Column("name")
    private String name;

    @Column("type")
    private String type;

    @Column("status")
    private String status;

    /**
     * 关联表字段 - 分类名称
     */
    @Column("category_name")
    private String categoryName;

    @Column("creation_date")
    private Date creationDate;
}

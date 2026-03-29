package {basePackage}.dao;

import com.definesys.mpaas.query.MpaasQuery;
import com.definesys.mpaas.query.db.PageQueryResult;
import {basePackage}.config.DatasourceUtil;
import {basePackage}.dto.ExampleQueryRequest;
import {basePackage}.pojo.Example;
import {basePackage}.vo.ExampleVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.util.CollectionUtils;
import org.springframework.util.StringUtils;

import java.util.Collection;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * 示例数据访问层（各种 MpaasQuery 用法参考）
 *
 * 规范要点：
 * 1. Dao 层为单类实现，不做接口 + impl 分离
 * 2. 使用 @Component 注解
 * 3. 通过 DatasourceUtil 获取 MpaasQuery 进行数据库操作
 * 4. Dao 层只负责数据库操作，不包含业务逻辑
 * 5. 直接使用 MpaasQuery 流式 API，禁止封装 commonXxx 等泛型方法
 * 6. 方法名应明确表达业务语义（如 getUserByEmail），而非泛型操作（如 commonQuery）
 * 7. 方法开头对关键参数做空值校验：查询单条返回 null，查询列表返回空集合，删除/更新直接 return
 *
 * 注意：本文件是写法参考，不要整体复制。按需生成实际业务需要的方法即可。
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class ExampleDao {

    private final DatasourceUtil datasourceUtil;

    // ==================== 插入 ====================

    /**
     * 插入单条记录
     */
    public void insert(Example example) {
        if (example == null) {
            return;
        }
        datasourceUtil.buildDefaultMpaasQuery().doInsert(example);
    }

    // ==================== 单条查询 ====================

    /**
     * 根据 document_id 查询单条记录
     */
    public Example getOneById(String documentId) {
        if (!StringUtils.hasText(documentId)) {
            return null;
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .eq("document_id", documentId)
                .doQueryFirst(Example.class);
    }

    // ==================== 更新 ====================

    /**
     * 根据条件更新（整体更新）
     */
    public Integer updateById(Example example) {
        if (example == null || !StringUtils.hasText(example.getDocumentId())) {
            return 0;
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .eq("document_id", example.getDocumentId())
                .doUpdate(example);
    }

    /**
     * 根据条件更新指定字段（通过字段列表）
     */
    public Integer updateFieldsById(Example example, List<String> fields) {
        if (example == null || !StringUtils.hasText(example.getDocumentId()) || CollectionUtils.isEmpty(fields)) {
            return 0;
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .update(fields)
                .eq("document_id", example.getDocumentId())
                .doUpdate(example);
    }

    /**
     * 链式更新多个字段（多次调用 .update() 分别指定字段和值）
     * 适用于只更新少量明确字段、不需要传入整个实体的场景
     */
    public Integer updateNameAndStatus(String documentId, String name, String status) {
        if (!StringUtils.hasText(documentId)) {
            return 0;
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .update("name", name)
                .update("status", status)
                .eq("document_id", documentId)
                .doUpdate(Example.class);
    }

    // ==================== 删除 ====================

    /**
     * 根据 document_id 删除（通过 Pojo 类）
     */
    public Integer deleteById(String documentId) {
        if (!StringUtils.hasText(documentId)) {
            return 0;
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .eq("document_id", documentId)
                .doDelete(Example.class);
    }

    /**
     * 根据条件删除（通过表名，适用于没有 Pojo 映射的场景）
     * ⚠️ 删除必须带条件，无条件删除会抛出 SW-180229 异常
     * doDelete() 返回值为 Integer，表示删除的行数
     */
    public Integer deleteByCondition(String name) {
        if (!StringUtils.hasText(name)) {
            return 0;
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .eq("name", name)
                .table("t_example")
                .doDelete();
    }

    // ==================== 批量操作 ====================

    /**
     * 批量插入
     * 使用 doBatchInsert 一次性插入多条记录
     */
    public void batchInsert(List<Example> exampleList) {
        if (CollectionUtils.isEmpty(exampleList)) {
            return;
        }
        datasourceUtil.buildDefaultMpaasQuery()
                .doBatchInsert(exampleList);
    }

    // ==================== 分页查询 ====================

    /**
     * 分页查询（精确匹配 + 日期范围）
     */
    public PageQueryResult pageQuery(int page, int pageSize, ExampleQueryRequest condition) {
        MpaasQuery mpaasQuery = datasourceUtil.buildDefaultMpaasQuery()
                .orderBy("creation_date", "desc");

        if (condition != null) {
            if (StringUtils.hasText(condition.getName())) {
                mpaasQuery.eq("name", condition.getName());
            }
            if (StringUtils.hasText(condition.getStatus())) {
                mpaasQuery.eq("status", condition.getStatus());
            }
            if (condition.getDateBegin() != null) {
                mpaasQuery.gteq("creation_date", condition.getDateBegin());
            }
            if (condition.getDateEnd() != null) {
                mpaasQuery.lteq("creation_date", condition.getDateEnd());
            }
        }

        return mpaasQuery.doPageQuery(page, pageSize, Example.class);
    }

    // ==================== 模糊查询 ====================

    /**
     * 模糊查询示例
     * like: 模糊匹配
     * likeNoCase: 不分大小写模糊匹配
     * startWith: 以 xxx 开头
     * endWith: 以 xxx 结尾
     */
    public List<Example> queryByNameLike(String name) {
        if (!StringUtils.hasText(name)) {
            return Collections.emptyList();
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .like("name", name)
                .orderBy("creation_date", "desc")
                .doQuery(Example.class);
    }

    // ==================== 指定字段查询（select）====================

    /**
     * 只查询指定字段
     */
    public List<Example> querySelectedFields(String name) {
        if (!StringUtils.hasText(name)) {
            return Collections.emptyList();
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .select("name", "type", "status")
                .like("name", name)
                .doQuery(Example.class);
    }

    // ==================== or / and 条件连接 ====================

    /**
     * or 条件连接：name 或 type 匹配
     */
    public List<Example> queryByNameOrType(String keyword) {
        if (!StringUtils.hasText(keyword)) {
            return Collections.emptyList();
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .or()
                .like("name", keyword)
                .like("type", keyword)
                .doQuery(Example.class);
    }

    /**
     * 混合使用 or 和 and
     * SQL: name like x or type like x and status = 'ACTIVE'
     */
    public List<Example> queryByMixedConditions(String keyword, String status) {
        if (!StringUtils.hasText(keyword) || !StringUtils.hasText(status)) {
            return Collections.emptyList();
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .or()
                .like("name", keyword)
                .like("type", keyword)
                .and()
                .eq("status", status)
                .doQuery(Example.class);
    }

    // ==================== 条件分组（conjuctionAnd / conjuctionOr） ====================

    /**
     * 条件分组示例
     * SQL: (name like x or type like x) and (status = 'ACTIVE' and description is not null)
     */
    public List<Example> queryWithGrouping(String keyword, String status) {
        if (!StringUtils.hasText(keyword) || !StringUtils.hasText(status)) {
            return Collections.emptyList();
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .or()
                .like("name", keyword)
                .like("type", keyword)
                .conjuctionAnd()
                .and()
                .eq("status", status)
                .isNotNull("description")
                .doQuery(Example.class);
    }

    // ==================== 多值查询（in / not in） ====================

    /**
     * in 查询：查询多个状态的记录
     */
    public List<Example> queryByStatusIn(Collection<String> statuses) {
        if (CollectionUtils.isEmpty(statuses)) {
            return Collections.emptyList();
        }
        return datasourceUtil.buildDefaultMpaasQuery()
                .in("status", statuses)
                .orderBy("creation_date", "desc")
                .doQuery(Example.class);
    }

    // ==================== 平台数据库查询（buildPlatformMpaasQuery） ====================

    /**
     * 从平台数据库查询用户信息（按账号或邮箱）
     * 使用场景：需要从平台库（xdap_manage_database）获取平台用户数据
     * 注意：仅在需要查询平台级数据时使用 buildPlatformMpaasQuery
     */
    public Object getUserByAccount(String account) {
        if (!StringUtils.hasText(account)) {
            return null;
        }
        return datasourceUtil.buildPlatformMpaasQuery()
                .or()
                .eq("account", account)
                .eq("email", account)
                .doQueryFirst(Object.class);
    }

    /**
     * 从平台数据库根据ID查询用户
     */
    public Object getUserById(String id) {
        if (!StringUtils.hasText(id)) {
            return null;
        }
        return datasourceUtil.buildPlatformMpaasQuery()
                .eq("id", id)
                .doQueryFirst(Object.class);
    }

    // ==================== 流程引擎数据库查询（buildDefaultActivitiMpaasQuery） ====================

    /**
     * 从 Activiti 流程引擎数据库查询流程实例
     * 使用场景：需要查询流程实例、审批记录等流程引擎数据
     * 注意：仅在需要查询流程引擎数据时使用 buildDefaultActivitiMpaasQuery
     */
    public List<Object> queryProcessInstanceBySubmitter(String submitter) {
        if (!StringUtils.hasText(submitter)) {
            return Collections.emptyList();
        }
        return datasourceUtil.buildDefaultActivitiMpaasQuery()
                .eq("submitter", submitter)
                .doQuery(Object.class);
    }

    // ==================== 原生 SQL 查询 ====================

    /**
     * 使用原生 SQL 进行复杂查询
     * 参数使用 #paramName 占位符，禁止字符串拼接
     */
    public List<Map<String, Object>> queryByCustomSql(String name, String status) {
        MpaasQuery mpaasQuery = datasourceUtil.buildDefaultMpaasQuery();
        StringBuilder sql = new StringBuilder("SELECT * FROM t_example WHERE 1=1");

        if (StringUtils.hasText(name)) {
            sql.append(" AND name = #name");
            mpaasQuery.setVar("name", name);
        }
        if (StringUtils.hasText(status)) {
            sql.append(" AND status = #status");
            mpaasQuery.setVar("status", status);
        }

        sql.append(" ORDER BY creation_date DESC");
        return mpaasQuery.sql(sql.toString()).doQuery();
    }

    // ==================== 视图查询 ====================

    /**
     * 使用数据库视图查询
     * 需要在对应的 VO 类上通过 @SQLQuery + @SQL 定义视图 SQL（参考 ExampleVO.java）
     * .view("exampleView") 指定 @SQL.view 的别名，.viewQueryMode(true) 进入视图模式
     */
    public PageQueryResult pageQueryByView(int page, int pageSize, String status) {
        return datasourceUtil.buildDefaultMpaasQuery()
                .view("exampleView")
                .viewQueryMode(true)
                .eq("status", status)
                .orderBy("creation_date", "desc")
                .doPageQuery(page, pageSize, ExampleVO.class);
    }
}

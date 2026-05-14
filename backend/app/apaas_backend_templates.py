"""aPaaS 后端自开发模版包标准骨架文件模版。

源自 `/Users/mars/低代码/平台自开发/03_后端自开发/后端自开发/` 三份文档：
- aPaaS-后端踩坑总结(同事版).md（16 坑）
- aPaaS-后端自开发快速入门.md
- aPaaS-后端自开发模版包打包规范.md

用于 init_apaas_backend_workspace MCP 工具一键脚手架，让 dolphin agent 写后端
自开发代码时直接绕过坑 5 / 6 / 7 / 15 / 16 五大死亡坑：
- 坑 7: @SpringBootApplication 放 src/main 让 aPaaS 发布卡死
- 坑 15: INSERT 必须用 POJO，不接受原生 SQL
- 坑 16: Entity 必须继承 BasePojo + initInsertIdentity（不然详情页空白）

所有模版用 {project_pkg} / {ProjectClass} / {project_name} 三个占位符渲染。
"""
from __future__ import annotations


def _camel_class(project_pkg: str) -> str:
    """leave-passport → LeavePassport（用作 Bean 类前缀，防坑 4 命名冲突）。"""
    parts = [p for p in project_pkg.replace("-", "_").split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "App"


# ─── pom.xml ──────────────────────────────────────────────────────────────
POM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>2.2.7.RELEASE</version>
        <relativePath/>
    </parent>

    <groupId>com.xdap</groupId>
    <artifactId>{project_pkg}</artifactId>
    <version>1.0</version>

    <properties>
        <maven.compiler.source>8</maven.compiler.source>
        <maven.compiler.target>8</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <java.version>1.8</java.version>
        <papaas.version>4.1.1-rc</papaas.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>com.xdap</groupId>
            <artifactId>motor-spring-boot-starter</artifactId>
            <version>1.2.8-RELEASE</version>
            <exclusions>
                <exclusion><artifactId>snakeyaml</artifactId><groupId>org.yaml</groupId></exclusion>
                <exclusion><artifactId>spring-beans</artifactId><groupId>org.springframework</groupId></exclusion>
                <exclusion><artifactId>netty-handler</artifactId><groupId>io.netty</groupId></exclusion>
                <exclusion><artifactId>netty-transport</artifactId><groupId>io.netty</groupId></exclusion>
                <exclusion><artifactId>spring-context</artifactId><groupId>org.springframework</groupId></exclusion>
                <exclusion><artifactId>netty-common</artifactId><groupId>io.netty</groupId></exclusion>
            </exclusions>
        </dependency>
        <dependency>
            <groupId>org.yaml</groupId>
            <artifactId>snakeyaml</artifactId>
            <version>2.0</version>
        </dependency>
        <dependency>
            <groupId>com.xdap</groupId>
            <artifactId>app</artifactId>
            <version>${{papaas.version}}</version>
            <exclusions>
                <exclusion>
                    <artifactId>azure-spring-boot-starter-storage</artifactId>
                    <groupId>com.azure.spring</groupId>
                </exclusion>
            </exclusions>
        </dependency>
        <dependency>
            <groupId>com.xdap</groupId>
            <artifactId>runtime</artifactId>
            <version>${{papaas.version}}</version>
            <exclusions>
                <exclusion><artifactId>app</artifactId><groupId>com.xdap</groupId></exclusion>
            </exclusions>
        </dependency>
        <dependency>
            <groupId>org.projectlombok</groupId>
            <artifactId>lombok</artifactId>
            <scope>provided</scope>
        </dependency>
    </dependencies>

    <repositories>
        <repository>
            <id>dcloud-public</id>
            <url>https://registry.dfy.definesys.cn/repository/maven-public/</url>
        </repository>
    </repositories>

    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <configuration>
                    <source>8</source>
                    <target>8</target>
                </configuration>
            </plugin>
        </plugins>
    </build>

    <profiles>
        <profile>
            <id>lib</id>
            <build>
                <resources>
                    <resource>
                        <directory>src/main/resources</directory>
                        <excludes>
                            <exclude>**/*.properties</exclude>
                            <exclude>**/*.yml</exclude>
                        </excludes>
                    </resource>
                </resources>
            </build>
        </profile>
        <profile>
            <id>single</id>
            <build>
                <plugins>
                    <plugin>
                        <groupId>org.springframework.boot</groupId>
                        <artifactId>spring-boot-maven-plugin</artifactId>
                    </plugin>
                </plugins>
                <resources>
                    <resource><directory>src/main/resources</directory></resource>
                </resources>
            </build>
        </profile>
    </profiles>

    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>com.xdap</groupId>
                <artifactId>defanyun-apaas-private</artifactId>
                <version>${{papaas.version}}</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
        </dependencies>
    </dependencyManagement>
</project>
"""


# ─── BasePojo.java ────────────────────────────────────────────────────────
BASEPOJO_JAVA = """\
package com.xdap.{project_pkg}.common;

import com.definesys.mpaas.query.annotation.Column;
import com.definesys.mpaas.query.annotation.SystemColumn;
import com.definesys.mpaas.query.annotation.SystemColumnType;
import com.definesys.mpaas.query.model.MpaasBasePojo;
import com.xdap.motor.entity.SnowflakeIdWorker;
import lombok.Data;

import java.util.Collection;
import java.util.Date;

/**
 * aPaaS 系统字段基类 — 业务 Entity 必须继承此类。
 *
 * 缺少 documentId / status / tenantId / formId 等系统字段会导致：
 *   - 数据 INSERT 成功，但 aPaaS 前台详情页空白
 *   - 列表页查询不到记录
 * 见踩坑总结坑 16。
 *
 * 用法：
 *   YourEntity e = new YourEntity();
 *   e.setFieldA("xxx");
 *   e.initInsertIdentity();           // 补 id + documentId + status=COMPLETED
 *   e.setTenantId(tenantId);          // 从 application.properties 注入
 *   e.setFormId(formId);              // 从 application.properties 注入
 *   e.setCreationDate(new Date());
 *   e.setLastUpdateDate(new Date());
 *   baseDao.query().doInsert(e);      // 必须 POJO，不接受原生 INSERT SQL
 */
@Data
public class BasePojo extends MpaasBasePojo {{

    @Column(value = "id")
    private String id;

    @Column(value = "document_id")
    private String documentId;

    @Column(value = "tab_doc_id")
    private String tabDocId;

    @Column(value = "status")
    private String status = "COMPLETED";

    @Column(value = "approver_id")
    private String approverId;

    @Column(value = "tenant_id")
    private String tenantId;

    @Column(value = "form_id")
    private String formId;

    @Column(value = "process_id")
    private String processId;

    @SystemColumn(SystemColumnType.OWNER)
    private String owner;

    @Column("created_by")
    @SystemColumn(SystemColumnType.CREATE_BY)
    private String createdBy;

    @Column("last_updated_by")
    @SystemColumn(SystemColumnType.LASTUPDATE_BY)
    private String lastUpdatedBy;

    @Column("creation_date")
    @SystemColumn(SystemColumnType.CREATE_ON)
    private Date creationDate;

    @Column("last_update_date")
    @SystemColumn(SystemColumnType.LASTUPDATE_ON)
    private Date lastUpdateDate;

    @Column("object_version_number")
    @SystemColumn(SystemColumnType.OBJECT_VERSION)
    private Integer objectVersionNumber;

    /** 插入前必调 — 补齐 id / documentId / status。 */
    public void initInsertIdentity() {{
        if (isBlank(this.id)) {{
            this.id = String.valueOf(SnowflakeIdWorker.nextExecId());
        }}
        if (isBlank(this.documentId)) {{
            this.documentId = String.valueOf(SnowflakeIdWorker.nextExecId());
        }}
        if (isBlank(this.status)) {{
            this.status = "COMPLETED";
        }}
    }}

    public static void initInsertIdentity(Collection<? extends BasePojo> entities) {{
        if (entities == null) return;
        for (BasePojo entity : entities) {{
            if (entity != null) entity.initInsertIdentity();
        }}
    }}

    private static boolean isBlank(String value) {{
        return value == null || value.trim().isEmpty();
    }}
}}
"""


# ─── BaseDao.java ─────────────────────────────────────────────────────────
BASEDAO_JAVA = """\
package com.xdap.{project_pkg}.common.dao;

import com.definesys.mpaas.query.MpaasQuery;
import com.xdap.runtime.service.RuntimeDatasourceService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/**
 * MpaasQuery 入口封装（多租户感知）。
 *
 * 关键 API 使用规范（见踩坑总结坑 9/10/13/14/15）：
 *   - 返回 Map：用无参 doQuery() / doQueryFirst()，不要传 Map.class / HashMap.class（坑 9 JPMS 反射拒绝）
 *   - 参数绑定：用 setOriginVar(name, value)，不要用 setVar（坑 10 加 va_ 前缀）
 *   - setOriginVar(name, null) 会崩，调前 v=v==null?"":v 兜底（坑 13）
 *   - INSERT 用 doInsert(pojo)，不接受原生 SQL（坑 15 SW-180228）
 *   - UPDATE/DELETE 用 doUpdate()/doDelete()，SQL 必须带 WHERE（坑 14 SW-180227）
 */
@Component
public class BaseDao {{

    @Autowired
    private RuntimeDatasourceService runtimeDatasourceService;

    public MpaasQuery query() {{
        return runtimeDatasourceService.buildTenantNoSchemaMpaasQuery();
    }}
}}
"""


# ─── {Project}UrlAllowConfig.java ─────────────────────────────────────────
URL_ALLOW_CONFIG_JAVA = """\
package com.xdap.{project_pkg}.config;

import com.xdap.api.moudle.custom.AllowUrlManage;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.Set;

/**
 * URL 白名单 — 不注册会被 aPaaS 平台拦截，所有自定义接口都 404。
 *
 * 路径规则：/custom/{{项目名}}/* — 必须跟 Controller 的 @RequestMapping 对齐。
 */
@Component
public class {ProjectClass}UrlAllowConfig implements AllowUrlManage {{

    @Override
    public Set<String> getCustomAllowUrls() {{
        Set<String> urlSet = new HashSet<>();
        urlSet.add("/custom/{project_pkg}/*");
        return urlSet;
    }}
}}
"""


# ─── Sample Entity / Service / Controller（让 agent 知道标准用法）─────────
SAMPLE_ENTITY_JAVA = """\
package com.xdap.{project_pkg}.sample.entity;

import com.definesys.mpaas.query.annotation.Column;
import com.definesys.mpaas.query.annotation.Style;
import com.definesys.mpaas.query.annotation.Table;
import com.xdap.{project_pkg}.common.BasePojo;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 示例 Entity — 仿照这个写你的业务表 Entity。
 *
 * 必须：
 *   - 继承 BasePojo（不是 MpaasBasePojo）
 *   - @Table(value="你的表名")
 *   - @Style(Upper2Underline=false)
 *   - 不要再声明 id 字段（BasePojo 已有）
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Table(value = "sample_table")
@Style(Upper2Underline = false)
public class SampleEntity extends BasePojo {{

    @Column(value = "sample_field")
    private String sampleField;
}}
"""

SAMPLE_SERVICE_JAVA = """\
package com.xdap.{project_pkg}.sample.service;

import com.xdap.{project_pkg}.common.dao.BaseDao;
import com.xdap.{project_pkg}.sample.entity.SampleEntity;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.List;
import java.util.Map;

/**
 * 示例 Service — 仿照这个写你的业务逻辑。
 *
 * 注意 Bean 名加 {ProjectClass} 前缀防跟 aPaaS 平台 Bean 冲突（见坑 4）。
 */
@Service("{project_pkg}SampleService")
@Slf4j
public class {ProjectClass}SampleService {{

    @Autowired
    private BaseDao baseDao;

    @Value("${{apaas.single.tenantId:}}")
    private String tenantId;

    @Value("${{sample.formId:}}")
    private String formId;

    // === 查询：返回 Map — 用无参 doQuery，不要传 Map.class（坑 9）===
    public Map<String, Object> getById(String id) {{
        return baseDao.query()
                .sql("SELECT * FROM sample_table WHERE document_id = :id")
                .setOriginVar("id", id == null ? "" : id)   // 坑 13: null 兜底
                .doQueryFirst();
    }}

    // === 查询：返回 Entity ===
    public List<SampleEntity> listByStatus(String status) {{
        return baseDao.query()
                .eq("status", status)
                .doQuery(SampleEntity.class);
    }}

    // === 子表查询 — 关联主表用 tab_doc_id（坑 11）===
    public List<Map<String, Object>> listChildren(String parentDocId) {{
        return baseDao.query()
                .sql("SELECT * FROM sample_child WHERE tab_doc_id = :pid")
                .setOriginVar("pid", parentDocId == null ? "" : parentDocId)
                .doQuery();
    }}

    // === 写入 — 必须 POJO + initInsertIdentity（坑 15/16）===
    public String insert(SampleEntity entity) {{
        entity.initInsertIdentity();              // ★ 必调
        entity.setTenantId(tenantId);
        entity.setFormId(formId);
        entity.setCreationDate(new Date());
        entity.setLastUpdateDate(new Date());
        baseDao.query().doInsert(entity);
        return entity.getId();
    }}

    // === UPDATE — 必须带 WHERE（坑 14）===
    public void update(String id, String newValue) {{
        baseDao.query()
                .sql("UPDATE sample_table SET sample_field = :val WHERE id = :id")
                .setOriginVar("val", newValue == null ? "" : newValue)
                .setOriginVar("id", id == null ? "" : id)
                .doUpdate();
    }}
}}
"""

SAMPLE_CONTROLLER_JAVA = """\
package com.xdap.{project_pkg}.sample.controller;

import com.xdap.api.config.Response;
import com.xdap.{project_pkg}.sample.service.{ProjectClass}SampleService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 示例 Controller — 仿照这个写你的接口。
 *
 * URL 路径规则（必须跟 UrlAllowConfig 一致）：/custom/{project_pkg}/xxx
 *
 * Bean 名加 {ProjectClass} 前缀防跟 aPaaS 平台 Bean 冲突（坑 4）。
 */
@RestController("{project_pkg}SampleController")
@RequestMapping("/custom/{project_pkg}")
@Slf4j
public class {ProjectClass}SampleController {{

    @Autowired
    private {ProjectClass}SampleService sampleService;

    @PostMapping("/query")
    public Response query(@RequestBody Map<String, Object> request) {{
        try {{
            String id = (String) request.get("id");
            Object data = sampleService.getById(id);
            return Response.ok().setData(data);
        }} catch (Exception e) {{
            log.error("查询失败", e);
            return Response.error("查询失败: " + e.getMessage());
        }}
    }}
}}
"""


# ─── 启动类 — 必须放 src/test/java（坑 7）─────────────────────────────────
SAMPLE_APPLICATION_JAVA = """\
package com.xdap.{project_pkg};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * ⚠️ 此启动类**必须**放在 src/test/java 下！
 *
 * 放到 src/main/java 会被打进生产 jar → aPaaS 平台加载模版包时扫到
 * @SpringBootApplication 触发二次 Spring 上下文初始化 → 与平台 Spring
 * 容器冲突死锁 → 「发布应用」永远卡在「上线中」无报错（坑 7）。
 *
 * 此文件仅用于本地 mvn spring-boot:run -P single 调试。
 */
@SpringBootApplication
public class {ProjectClass}Application {{
    public static void main(String[] args) {{
        SpringApplication.run({ProjectClass}Application.class, args);
    }}
}}
"""


# ─── application.properties ──────────────────────────────────────────────
APPLICATION_PROPERTIES = """\
# 本地调试用 — 打包 -P lib 时被排除，不进生产 jar

server.port=9092

# aPaaS 租户（aPaaS 后台拿）
apaas.single.tenantId={your_tenant_id}
apaas.single.appId={your_app_id}

# 表单 formId（aPaaS 后台 → 表单管理 拿）
sample.formId={your_form_id}
"""


# ─── README.md（agent 自查 + 用户上手）──────────────────────────────────
README_MD = """\
# {project_pkg}

aPaaS 后端自开发模版包（papaas 4.1.1-rc / Java 8 / Spring Boot 2.2.7）。

## 上传方式

```bash
mvn clean package -P lib -DskipTests
# 产物 target/{project_pkg}-1.0.jar（20-100KB 薄 jar）
```

上传：aPaaS 后台 → 应用详情 → 高级设置 → **后端自开发模版包**（不是插件管理）→ 上传 → 重新发布应用。

## 16 坑速查（点踩坑总结看详细）

1. 下拉/单选字段存的是 JSON 数组 `["code"]`，SQL 用 `JSON_UNQUOTE(JSON_EXTRACT(f,'$[0]')) = 'code'` 或 `LIKE '%code%'`，不能用 `= 'code'`
2. 数据字典字段存的是 valueCode 不是 valueName — 显示名需 JOIN apaas_data_dictionary_value
3. 人员字段存 user.id — 显示需 JOIN xdap_users
4. Bean 类名加项目前缀防冲突（如 `{ProjectClass}SampleService` 不是 `SampleService`）
5. 本地启动要排除 Druid / XdapProcess 等 autoconfigure + 配置雪花 ID
6. 本地调试用 JdbcTemplate，部署后用 RuntimeDatasourceService
7. **启动类必须放 `src/test/java`** — 放 main 下 aPaaS 发布卡死「上线中」无报错
8. 历史数据可能不是合法 JSON，`JSON_EXTRACT` 配 `IF(JSON_VALID(f),...)` 兜底
9. **MpaasQuery 返回 Map 用无参 `doQuery()`** — 别传 `Map.class` / `HashMap.class`（Java 17 JPMS 反射拒绝）
10. **参数绑定用 `setOriginVar`** — `setVar` 会自动加 `va_` 前缀导致占位符匹配不上
11. **aPaaS 子表关联主表字段是 `tab_doc_id`** — 不是 `parent_id` / `main_id` / `master_id`
12. aPaaS 业务字段在数据库列名不可预测（`field_code` 或 `f_field_code`），开发前先 `SELECT * FROM tbl LIMIT 1` 看列名
13. **`setOriginVar(name, null)` 会崩** — 绑定前 `v=v==null?"":v` 兜底
14. **INSERT 用 `doInsert()`，UPDATE/DELETE 用 `doUpdate()/doDelete()` 且必须带 WHERE**（DML 方法搞错抛 SW-180227）
15. **INSERT 必须造 POJO Entity，不接受原生 INSERT SQL**（SW-180228）
16. **Entity 必须继承 BasePojo 且 `initInsertIdentity()` + 设 tenantId/formId/creationDate** — 缺一个详情页都看不到数据

## URL 调用路径

| 场景 | 路径 |
|---|---|
| 外部系统 / Postman | `/apaas/backend/model/{{app}}/custom/{project_pkg}/xxx` |
| aPaaS 前端脚本 fetch | `/app/model/{{app}}/custom/{project_pkg}/xxx` |
| aPaaS 服务集成（按钮事件） | `/apaas/backend/model/{{app}}/custom/{project_pkg}/xxx` |

Controller `@RequestMapping` 只写 `/custom/{project_pkg}/xxx`，平台前缀自加。

## 上传前 checklist

- [ ] 启动类在 `src/test/java`（不在 src/main/java）
- [ ] Entity 继承 `BasePojo`（不是 `MpaasBasePojo`）
- [ ] INSERT 前调 `initInsertIdentity()` + 设 tenantId/formId
- [ ] 查询用无参 `doQuery()` + `setOriginVar`，null 兜底
- [ ] UPDATE/DELETE SQL 带 WHERE
- [ ] 子表关联用 `tab_doc_id`
- [ ] Bean 名带项目前缀
- [ ] `mvn package -P lib`（薄 jar，20-100KB）
"""


def render_all_templates(project_pkg: str, tenant_id: str = "", app_id: str = "",
                         form_id: str = "") -> dict[str, str]:
    """渲染所有模版文件，返回 {file_path: content} 字典。

    project_pkg: 项目英文短名（kebab-case），如 'leave-passport'。会做 underline
                 normalize 用作 Java 包名/Bean 前缀。
    """
    # Java 包名禁止 -，全转 _
    pkg = project_pkg.replace("-", "_").lower()
    cls = _camel_class(project_pkg)

    fmt = {
        "project_pkg": pkg,
        "ProjectClass": cls,
        "your_tenant_id": tenant_id or "<填租户 ID>",
        "your_app_id": app_id or "<填应用 ID>",
        "your_form_id": form_id or "<填表单 ID>",
    }

    pkg_path = pkg  # com/xdap/{pkg_path}/...

    return {
        "pom.xml": POM_XML.format(**fmt),
        f"src/main/java/com/xdap/{pkg_path}/common/BasePojo.java": BASEPOJO_JAVA.format(**fmt),
        f"src/main/java/com/xdap/{pkg_path}/common/dao/BaseDao.java": BASEDAO_JAVA.format(**fmt),
        f"src/main/java/com/xdap/{pkg_path}/config/{cls}UrlAllowConfig.java": URL_ALLOW_CONFIG_JAVA.format(**fmt),
        f"src/main/java/com/xdap/{pkg_path}/sample/entity/SampleEntity.java": SAMPLE_ENTITY_JAVA.format(**fmt),
        f"src/main/java/com/xdap/{pkg_path}/sample/service/{cls}SampleService.java": SAMPLE_SERVICE_JAVA.format(**fmt),
        f"src/main/java/com/xdap/{pkg_path}/sample/controller/{cls}SampleController.java": SAMPLE_CONTROLLER_JAVA.format(**fmt),
        f"src/test/java/com/xdap/{pkg_path}/{cls}Application.java": SAMPLE_APPLICATION_JAVA.format(**fmt),
        "src/main/resources/application.properties": APPLICATION_PROPERTIES.format(**fmt),
        "README.md": README_MD.format(**fmt),
    }

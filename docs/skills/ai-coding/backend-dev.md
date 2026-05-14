# aPaaS 后端自开发模版包 — agent 知识库

> v0.1 / 2026-05-14 — 沉淀自同事 16 坑总结 + 快速入门 + 打包规范三份文档
> 适用：dolphin agent（vibe / coding） 帮用户做 aPaaS 后端自开发时引用

## 关键概念：什么是"后端自开发模版包"

aPaaS 平台允许用户上传一个**薄 jar**（20-100KB），平台运行时把它加载到自己的 JVM 里，扩展应用的后端接口能力。

跟"插件管理"是两个东西：
- **后端自开发模版包**（本文）：上传入口在「应用详情 → 高级设置 → 后端自开发模版包」，aPaaS 版本 `4.1.1-rc`，依赖 `motor-spring-boot-starter` + `runtime` + `app`
- 插件管理（旧）：aPaaS `3.2.x`，独立 Spring Boot

**选错模式 = 404/405/不加载**。新项目都走"后端自开发模版包"。

---

## 一键脚手架（agent 优先调）

要让用户做后端自开发：**第一步必须调 `init_apaas_backend_workspace` 工具**。
它一次性写入 10 个标准文件直接绕过 5 大死亡坑（P5/P6/P7/P15/P16）：

```
ws_id: <AI Coding workspace id>
project_name: <kebab-case 项目名，如 leave-passport>
apaas_tenant_id: <可空，application.properties 占位>
apaas_app_id:    <可空>
sample_form_id:  <可空>
```

写入产物：
- `pom.xml`（papaas 4.1.1-rc + motor 1.2.8 + lib/single profile）
- `src/main/java/com/xdap/{pkg}/common/BasePojo.java`（系统字段基类）
- `src/main/java/com/xdap/{pkg}/common/dao/BaseDao.java`
- `src/main/java/com/xdap/{pkg}/config/{Project}UrlAllowConfig.java`（URL 白名单）
- `src/main/java/com/xdap/{pkg}/sample/{entity,service,controller}/...`（示例三层）
- `src/test/java/com/xdap/{pkg}/{Project}Application.java`（启动类，**test 路径**）
- `src/main/resources/application.properties`
- `README.md`

之后再让 agent 自己用 `read_workspace_file` / `write_workspace_files` / `edit_workspace_files` 改示例代码成真业务。

---

## 上传前必跑 lint

调 `lint_apaas_backend_workspace` 扫一遍，**默认 publish 时也会自动 lint**（skip_lint=true 跳但不推荐）。

lint 能抓的（9 个 grep-able 坑）：

| 坑号 | 严重 | 检测 |
|---|---|---|
| P1 | warn | 下拉/单选字段 `= 'code_gN'` 比较 — apaas 存的是 JSON 数组 |
| P7 | **fatal** | `@SpringBootApplication` 出现在 `src/main/java` 下 |
| P9 | **fatal** | `doQuery(Map.class)` / `doQuery(HashMap.class)` |
| P10 | warn | `setVar()` — 会加 va_ 前缀 |
| P11 | warn | `WHERE parent_id`/`main_id` — 子表关联应该是 `tab_doc_id` |
| P13 | **fatal** | `setOriginVar(_, null)` 字面 null |
| P14 | **fatal** | `INSERT INTO` 后跟 `.doUpdate()` |
| P15 | **fatal** | `INSERT INTO` SQL + `.doInsert()` 无 POJO |
| P16 | warn | 业务类直接 `extends MpaasBasePojo` — 应继承项目 BasePojo |

lint 抓不到（需要 review 或 publish 后跑）：
- P2/P3 数据字典 / 用户 ID 翻译
- P5/P6 本地 application.yml 配置
- P8 JSON 历史脏数据
- P12 业务字段列名运行时检测

---

## 16 坑完整速查（搜索引擎用）

> 详细见同事原文档 `aPaaS-后端踩坑总结(同事版).md`

| # | 坑 | 一句话 |
|---|---|---|
| 1 | 下拉字段是 JSON 数组 | SQL 用 `JSON_UNQUOTE(JSON_EXTRACT(f,'$[0]')) = 'code'` 或 `LIKE '%code%'` |
| 2 | 字典字段存 valueCode 非 valueName | 显示名 JOIN `apaas_data_dictionary_value` |
| 3 | 人员字段存 user.id | 显示名 JOIN `xdap_users` |
| 4 | Bean 类名冲突 | 类名加项目前缀（`LeavePassportService` 不是 `Service`） |
| 5 | 本地启动配置 | autoconfigure exclude Druid / XdapProcess + 配雪花 ID |
| 6 | 本地 vs 部署 datasource | 本地 JdbcTemplate / 部署 RuntimeDatasourceService |
| **7** | **启动类位置** | **必须 `src/test/java`，不在 `src/main`**（否则发布卡死） |
| 8 | JSON 历史脏数据 | `IF(JSON_VALID(f), JSON_EXTRACT(...), f)` 兜底 |
| **9** | **doQuery 传 Map.class** | **用无参 `doQuery()` / `doQueryFirst()`** |
| 10 | setVar 加 va_ 前缀 | 改用 `setOriginVar` |
| **11** | **子表关联** | **用 `tab_doc_id`，不是 parent_id / main_id** |
| 12 | 业务字段列名不可预测 | `SELECT * LIMIT 1` 先看真实列名 |
| **13** | **setOriginVar(null)** | **`v == null ? "" : v` 兜底** |
| **14** | **INSERT 用 doInsert** | **不是 doUpdate**（DML 方法对齐） |
| **15** | **INSERT 必须 POJO** | **`doInsert(entity)`，不接受原生 SQL** |
| **16** | **Entity 必须继承 BasePojo** | **+ `initInsertIdentity()` + 设 tenantId/formId** |

---

## 上传 / URL 路径

```bash
mvn clean package -P lib -DskipTests   # 产物：target/{pkg}-1.0.jar （薄 jar 20-100KB）
```

aPaaS 后台 → 应用详情 → **高级设置** → **后端自开发模版包** → 上传 → 重新发布。

URL 路径三种场景：

| 场景 | 路径 |
|---|---|
| 外部 / Postman | `/apaas/backend/model/{app}/custom/{pkg}/xxx` |
| aPaaS 前端 fetch | `/app/model/{app}/custom/{pkg}/xxx` |
| 服务集成（按钮事件） | `/apaas/backend/model/{app}/custom/{pkg}/xxx` |

Controller `@RequestMapping` 只写 `/custom/{pkg}/xxx`，平台前缀自加。

---

## agent 推荐工作流

```
1. dolphin agent 跟用户对齐需求（"做个请假申请的后端审批接口"）
   ↓
2. agent 调 create_dev_workspace(scene_type="backend-api", project_name="leave-approval")
   ↓
3. agent 调 init_apaas_backend_workspace(ws_id, project_name="leave-approval", apaas_app_id="...")
   ↓
4. agent 调 read_workspace_file 看 sample/Controller/Service，照葫芦改业务字段
   ↓
5. agent 调 write_workspace_files / edit_workspace_files 改代码
   ↓
6. agent 调 lint_apaas_backend_workspace(ws_id)  ← 自查
   ↓ (fatal=0)
7. agent 调 publish_dev_workspace(ws_id, env_id)  ← 内置 lint 兜底
   ↓
8. agent 调 enable_apaas_self_dev_config + attach_dev_packages_to_apaas_app + republish_apaas_app
   ↓
9. agent 引用应用「访问授权」工具：set_apaas_app_access (object_type=ALL 全员可见)
```

---

## 相关工具

| 工具 | 用途 |
|---|---|
| `init_apaas_backend_workspace` | 写入标准骨架 |
| `lint_apaas_backend_workspace` | 静态扫坑 |
| `publish_dev_workspace`        | build + 上传（内置 lint） |
| `enable_apaas_self_dev_config` | 开启应用自开发开关 |
| `attach_dev_packages_to_apaas_app` | 关联 jar 到应用 |
| `republish_apaas_app`          | 重发布让组件生效 |
| `set_apaas_app_access`         | 设应用可见性 |
| `read_workspace_file` / `write_workspace_files` / `edit_workspace_files` / `glob_workspace` / `grep_workspace` / `run_workspace_command` | workspace 文件操作 |

---

## 给 dolphin agent prompt 的引用片段

在 vibe / coding agent prompt 里加：

```
做 aPaaS 后端自开发（papaas 4.1.1-rc 模版包）时，按 docs/skills/apaas-backend-dev.md：
1. 先 init_apaas_backend_workspace 拿标准骨架（绕过 5 大死亡坑）
2. 改代码时严格遵守 16 坑速查（启动类必须 src/test、INSERT 必须 POJO、Entity
   必须继承 BasePojo + initInsertIdentity、setOriginVar 不是 setVar、子表关联用
   tab_doc_id 等）
3. publish 前调 lint_apaas_backend_workspace 自查
4. 用户没明确说要后端时不要主动开后端 — 业务能用 SPEC 解决就别引入后端代码
```

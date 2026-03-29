# CLAUDE.md

本文件为 Claude Code 的项目级指导文件，帮助 AI 理解项目上下文并遵循团队规范。

## 项目概述

这是一个基于 **Spring Boot 2.2.7.RELEASE + Java 8** 的后端开发脚手架，使用 Maven 管理依赖。项目基于公司自研的**倚天开发框架**（Definesys MpaaS）进行开发，集成了倚天的数据库操作（MpaasQuery）、异常处理（XDapBizException）、统一响应（Response）等能力。

## 技术栈

- **语言**：Java 8
- **框架**：Spring Boot 2.2.7.RELEASE
- **构建工具**：Maven
- **数据库操作**：倚天框架 MpaasQuery（链式 API + 原生 SQL）
- **外部集成**：OpenFeign（FeignClient）
- **异常处理**：XDapBizException + BaseExceptionEnumInterface 异常枚举
- **响应封装**：com.definesys.mpaas.common.http.Response
- **代码简化**：Lombok（@Data、@RequiredArgsConstructor、@Slf4j）

## 项目结构

```
├── .claude/
│   ├── rules/          # 开发规范（自动加载），包含编码规范、开发行为规范、MpaasQuery 操作参考
│   └── skills/         # 可调用的技能，包含项目初始化、业务代码生成、FeignClient 生成等
├── examples/           # 参考代码模板，包含各层标准代码示例，使用 {basePackage} 占位符
├── src/main/java/{basePackage}/  # 业务代码（初始化后生成）
├── src/main/resources/           # 配置文件
├── pom.xml                       # Maven 配置（初始化后生成）
├── CLAUDE.md                     # 本文件
└── README.md                     # 项目说明
```

## 项目状态判断

AI 打开项目后，应先判断项目是否已初始化：

- **未初始化**：项目根目录下没有 `pom.xml`，且 `src/main/java` 下没有业务代码目录 → 应引导用户执行 `project-init` skill，并确认 `basePackage`
- **已初始化**：`pom.xml` 和 `src/main/java/{basePackage}` 已存在 → 直接进入业务开发，根据用户需求调用对应 skill 或按规范编写代码

## 核心规范（快速参考）

### 分层架构

```
Controller → Service（接口 + Impl） → Dao → 数据库
```

- **Controller**：只接收请求和返回结果，禁止业务逻辑，禁止调用 Dao
- **Service**：业务逻辑编排，禁止直接操作数据库
- **Dao**：数据库操作，单类实现（不做接口+impl分离），通过 DatasourceUtil 获取 MpaasQuery

### 关键约束

1. `basePackage` 必须以 `com.xdap.` 开头，不允许其他写法
2. 所有 Controller 接口路径必须以 `/custom` 开头
3. 依赖注入使用 `@RequiredArgsConstructor` + `final` 字段，禁止 `@Autowired`
4. 业务异常使用 `XDapBizException` + 异常枚举，禁止 `throw new RuntimeException()`
5. 统一响应使用 `Response.ok()`，禁止自定义响应结构
6. 日志使用 `@Slf4j`，占位符 `{}`，禁止字符串拼接
7. 实体类继承 `MainCommonPo`，使用 `@Table` + `@Column` 注解，只需声明业务字段
8. 新增记录时必须调用 `setBaseField()` 初始化系统字段（id、document_id、owner、时间戳等）
9. `setBaseField()` 中的 `formId` 是一个固定值，需业务方在开发前提供

## Skills 使用指南

| 场景 | 使用的 Skill |
|------|-------------|
| 初始化新项目 | `project-init` — 需提供 basePackage |
| 业务代码开发（按需生成） | `crud-generator` — 描述业务需求，按需生成各层代码 |
| 集成第三方接口 | `feign-client-generator` — 需提供接口信息 |
| 添加异常定义 | `exception-generator` — 需提供模块名和异常列表 |
| 完善脚手架 | `scaffold-improve` — 开发过程中纠错、补充规范和示例 |

## Examples 使用说明

`examples/` 目录下包含各层代码的参考模板，作为代码生成的风格基准。

- **生成前先参考**：生成业务代码前，应先读取对应层的 example 文件了解基本结构和风格
- **风格对齐**：生成的代码在类结构、注解用法、注释风格上应与 example 保持一致，但不必生搬硬套，可根据实际业务场景合理调整
- **占位符替换**：模板中的 `{basePackage}` 替换为项目实际的 basePackage

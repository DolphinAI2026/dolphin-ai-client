# aPaaS 后端自开发接口开发指南

## 概述
后端自开发使用标准SpringBoot项目开发，打包为jar上传到平台。

## 核心规范
1. **包名**: 必须以 `com.xdap` 开头，不可与系统包名重复
2. **接口路径**: 必须以 `/custom` 开头
3. **白名单**: 必须实现 `AllowUrlManage` 接口
4. **Maven仓库**: https://registry.dfy.definesys.cn/repository/maven-public/

## 不可用的系统包名
com.xdap.admin, com.xdap.api, com.xdap.app, com.xdap.common,
com.xdap.gateway-instead, com.xdap.integration, com.xdap.oauth,
com.xdap.runtime, com.xdap.plugins 等

## 基础服务
- `RuntimeAppContextService` - getCurrentAppId/TenantId/UserId/Token
- `RuntimeUserService` - queryLoginUserVo()
- `RuntimeDatasourceService` - buildTenantMpaasQuery/buildBusinessMpaasQuery
- `RuntimeTokenService` - createToken/verifyToken

## 打包部署
1. `mvn clean package -Dmaven.test.skip=true -P lib`
2. 在后台管理 → 扩展功能 → 自开发管理上传jar
3. 在应用高级设置中关联自开发包
4. 重新发布应用

## 注意事项
- 白名单接口不能使用 getCurrentUserId/getCurrentToken
- 多个自开发jar中bean名称和接口路径不可重复
- -P lib 打包不含第三方依赖，-P single 打包含依赖可本地启动

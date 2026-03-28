# aPaaS-TMS 后端自开发 项目汇总与开发指南

> 本文档基于当前代码工程梳理，旨在帮助开发者快速理解项目全貌，并能照此指南从0到1完成新业务接口的开发。

---

## 一、项目概述

| 项目 | 说明 |
|------|------|
| 项目名称 | apaas-tms（麦田能源 TMS 运输管理系统） |
| 技术栈 | Spring Boot 2.2.7 + Maven + MySQL + MongoDB |
| 平台集成 | aPaaS 低代码平台（definesys） |
| 前端对接 | 微信小程序（司机端）+ aPaaS 平台页面（管理端） |
| 启动端口 | 9092 |
| 核心业务 | 物流预约管理（预约→签到→叫号→入厂→装卸货→出厂） |

---

## 二、模块结构

```
apaas-tms/                          # 根POM（com.definesys:apaas-tms）
│
├── pom.xml                         # 父POM，管理三个子模块和公共依赖
│
├── apaas-app/                      # 【启动模块】Spring Boot 入口
│   ├── pom.xml                     # 依赖 apaas-tms-service
│   └── src/main/
│       ├── java/com/xdap/
│       │   ├── CustomApplication.java      # @SpringBootApplication 启动类
│       │   └── RestTemplateConfig.java     # RestTemplate 配置（30min超时）
│       └── resources/
│           └── application.properties      # 所有配置（DB/Redis/MQ/微信等）
│
├── apaas-sdk/                      # 【SDK模块】aPaaS平台能力封装（一般不改动）
│   ├── pom.xml                     # 依赖 query-mongodb（aPaaS核心SDK）
│   └── src/main/java/com/xdap/
│       ├── app/moudle/login/       # 登录服务（LoginService）
│       ├── common/                 # 会话管理、JWT工具、MongoDB数据源
│       ├── motor/exception/        # 异常体系（XDapBizException等）
│       ├── function/moudle/        # 用户DAO、OAuth DAO
│       └── api/                    # 数据源服务、URL白名单接口、常量
│
├── apaas-tms-service/              # ★【业务模块】核心开发区域
│   ├── pom.xml                     # 依赖 apaas-sdk
│   └── src/main/java/com/xdap/tms/
│       ├── config/                 # 配置类
│       │   ├── CustomDataSourceConfig.java   # 注入 MpaasQueryFactory
│       │   └── TmsUrlAllowConfig.java        # ★ URL白名单注册
│       ├── dao/
│       │   └── CommDao.java                  # ★ 通用数据访问层（核心）
│       ├── entity/
│       │   └── ApaasDatasourceEntity.java    # 数据源实体
│       ├── common/
│       │   ├── enums/
│       │   │   ├── CurrentStatusEnum.java    # 预约当前状态枚举（8种）
│       │   │   └── VehicleStatusEnum.java    # 车辆流水状态枚举（10种）
│       │   └── utils/
│       │       └── SnowflakeIdGenerator.java # 雪花ID生成器
│       ├── service/
│       │   ├── SyncLogService.java           # 同步日志服务
│       │   └── AsyncSyncLogService.java      # 异步日志包装
│       ├── appointment/                      # ★ 预约查询模块（微信小程序调用）
│       │   ├── controller/AppointmentController.java
│       │   ├── model/                        # Request/Response 模型
│       │   └── service/
│       │       ├── AppointmentService.java   # 预约查询业务逻辑
│       │       └── WxAuthService.java        # 微信认证服务
│       └── operation/                        # ★ 状态推进模块（aPaaS平台调用）
│           ├── controller/OperationController.java
│           ├── model/                        # Request/Response + ActionEnum
│           └── service/OperationService.java # 状态机执行逻辑
```

### 模块依赖关系

```
apaas-app（启动）
  └── apaas-tms-service（业务）
        └── apaas-sdk（平台SDK）
              └── query-mongodb（aPaaS底层）
```

> **日常开发只需关注 `apaas-tms-service` 模块**，apaas-sdk 和 apaas-app 一般不需要改动。

---

## 三、核心组件详解

### 3.1 CommDao — 通用数据访问层

**位置**: `com.xdap.tms.dao.CommDao`

这是所有业务数据操作的核心入口，封装了 HikariCP 连接池 + Sql2o，提供以下方法：

| 方法 | 说明 | 使用场景 |
|------|------|---------|
| `queryForList(sql, params)` | 执行查询，返回 `List<Map<String, Object>>` | 所有查询操作 |
| `executeSql(sql, params)` | 执行单条 INSERT/UPDATE/DELETE | 单条写操作 |
| `executeBatchSql(sql, batchParams)` | 批量执行（内部1000条一批） | 批量写入 |
| `executeDeleteAndBatchInsert(...)` | 事务性删除+批量插入 | 全量同步场景 |
| `buildTmsdbQuery()` | 获取 MpaasQuery 实例 | 需要用MpaasQuery API时 |

**使用示例**：

```java
@Autowired
private CommDao commDao;

// 查询
String sql = "SELECT * FROM table_name WHERE field = :param LIMIT 10";
Map<String, Object> params = new HashMap<>();
params.put("param", "value");
List<Map<String, Object>> rows = commDao.queryForList(sql, params);

// 更新
String updateSql = "UPDATE table_name SET field1 = :val WHERE id = :id";
Map<String, Object> updateParams = new HashMap<>();
updateParams.put("val", "newValue");
updateParams.put("id", "123");
commDao.executeSql(updateSql, updateParams);
```

**关键约定**：
- SQL 参数使用 `:paramName` 命名参数风格（Sql2o）
- 查询结果为 `List<Map<String, Object>>`，需手动取值转换
- 数据源配置来自 `application.properties` 的 `spring.datasource.*`

### 3.2 Response — 统一响应封装

**来源**: `com.definesys.mpaas.common.http.Response`（aPaaS 平台SDK提供）

```java
// 成功，带数据
return Response.ok().setData(data);

// 成功，无数据
return Response.ok().setData(null);

// 失败
return Response.error("错误描述信息");
```

### 3.3 SnowflakeIdGenerator — 全局唯一ID生成

```java
// 生成 long 类型 ID
long id = SnowflakeIdGenerator.generateId();

// 生成 String 类型 ID
String idStr = SnowflakeIdGenerator.generateIdStr();
```

### 3.4 异常处理

```java
// 业务异常（SDK提供）
throw new XDapBizException("业务异常描述");

// 运行时异常（当前项目中更常用的写法）
throw new RuntimeException("操作失败: " + reason);
```

### 3.5 数据字典查询

项目中大量字段用编码存储，需要通过数据字典翻译为中文名称：

```java
private String lookupDictValue(String dictCode, String valueCode) {
    String sql = "SELECT v.value_name FROM apaas_data_dictionary d " +
            "INNER JOIN apaas_data_dictionary_value v ON d.id = v.dictionary_id " +
            "WHERE d.dictionary_code = :dictCode AND v.value_code = :valueCode LIMIT 1";
    Map<String, Object> params = new HashMap<>();
    params.put("dictCode", dictCode);
    params.put("valueCode", valueCode);
    List<Map<String, Object>> list = commDao.queryForList(sql, params);
    if (list != null && !list.isEmpty()) {
        return Objects.toString(list.get(0).get("value_name"), null);
    }
    return null;
}
```

**已有字典编码对照**：

| dictCode | 含义 | 示例值 |
|----------|------|--------|
| `clcurstatus` | 预约当前状态 | 01=预约中, 02=待签到, 03=待入门... |
| `clcc` | 车辆尺寸 | 编码→名称 |
| `fktype` | 访客类型 | 01=访客预约, 02=送货预约, 03=提货预约 |
| `yytype` | 预约类型 | 编码→名称 |

### 3.6 JSON数组字段处理

数据库中 `visitorstatus`、`fvehiclestatus` 等字段以 JSON 数组格式存储（如 `["01"]`），需要特殊处理：

```java
// Java侧解析：去掉 [""] 包装
private String parseJsonArrayValue(String value) {
    if (value == null) return null;
    value = value.trim();
    if (value.startsWith("[") && value.endsWith("]")) {
        String inner = value.substring(1, value.length() - 1).trim();
        if (inner.startsWith("\"") && inner.endsWith("\"")) {
            return inner.substring(1, inner.length() - 1);
        }
        return inner;
    }
    return value;
}

// 写入时需要包装回 JSON 数组格式
params.put("visitorstatus", "[\"03\"]");
```

```sql
-- SQL侧提取：使用 MySQL JSON 函数
JSON_UNQUOTE(JSON_EXTRACT(fvehiclestatus, '$[0]'))
```

---

## 四、已有业务模块详解

### 4.1 预约查询模块（appointment）

**调用方**: 微信小程序（司机端）
**路由前缀**: `/custom/tms/appointment`

#### 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| `/phone/decrypt` | POST | 微信手机号解密（phoneCode → 明文手机号） |
| `/current` | POST | 查询当前最新未完成预约（集成鉴权+解密+查询） |
| `/detail` | POST | 根据预约编号查预约详情 |
| `/history` | POST | 分页查询历史预约记录 |

#### 请求/响应模型

**AppointmentQueryRequest**（/current 接口入参）：
```json
{
  "code": "微信登录code（必填，用于鉴权）",
  "phoneCode": "微信getPhoneNumber的code（与fmobile二选一）",
  "fmobile": "手机号明文（与phoneCode二选一）"
}
```

**AppointmentCurrentResponse**（/current、/detail 返回数据）：
```json
{
  "freservationno": "预约编号",
  "fmobile": "手机号",
  "fplatenumber": "车牌号",
  "visitorstatus": "当前状态编码",
  "visitorstatusName": "当前状态名称（字典翻译）",
  "fparkid_fname": "园区名称",
  "fvehiclesize": "车辆尺寸（字典翻译）",
  "fapplytype": "预约类型（字典翻译）",
  "fvisitortype": "访客类型（字典翻译）",
  "freservationtime": "预约时间",
  "fsignintime": "签到时间",
  "fqueueno": "排队号（仅待入门状态）",
  "fwaitcount": "前方等待数",
  "qrcode_str": "二维码内容",
  "qrcode": "二维码图片",
  "fdrivername": "司机姓名",
  "statusTimeline": [
    {
      "statusCode": "状态编码",
      "statusName": "状态名称",
      "time": "完成时间",
      "completed": true,
      "current": false,
      "skipped": false
    }
  ]
}
```

#### 认证流程

```
微信小程序
  │
  ├─ wx.login() 获取 code ──→ WxAuthService.validateCode(code) 验证身份
  │
  ├─ wx.getPhoneNumber() 获取 phoneCode ──→ WxAuthService.decryptPhoneNumber(phoneCode) 解密手机号
  │
  └─ 用手机号查询业务数据
```

#### 核心SQL逻辑

```sql
-- 查询最新未完成预约（排除已出厂的）
SELECT a.* FROM tms_visitor_appointment a
WHERE (a.fmobile = :fmobile OR a.visitorphone = :fmobile)
AND NOT EXISTS (
  SELECT 1 FROM tms_vehicle_realtime_record r
  WHERE r.freservationno = a.freservationno
  AND JSON_UNQUOTE(JSON_EXTRACT(r.fvehiclestatus, '$[0]')) = '09'
)
ORDER BY a.freservationno DESC LIMIT 1
```

### 4.2 状态推进模块（operation）

**调用方**: aPaaS 平台前端（管理端）
**路由前缀**: `/custom/tms/operation`

#### 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| `/action` | POST | 执行预约状态推进（状态机） |

#### 请求/响应模型

**ActionRequest**：
```json
{
  "freservationno": "预约编号",
  "action": "动作编码（sign_in / unload_start / load_start / unload_done / load_done）"
}
```

**ActionResponse**：
```json
{
  "freservationno": "预约编号",
  "action": "执行的动作",
  "statusName": "状态名称",
  "time": "操作时间"
}
```

#### 状态机定义（ActionEnum）

| action | 动作名称 | 前置状态(visitorstatus) | 目标状态(visitorstatus) | 流水状态(fvehiclestatus) |
|--------|---------|----------------------|----------------------|------------------------|
| `sign_in` | 扫码签到 | 02（待签到） | 03（待入门） | 02（已签到） |
| `unload_start` | 开始卸货 | 04（待卸货） | 07（卸货中） | 05（开始卸货） |
| `load_start` | 开始装货 | 05（待装货） | 08（装货中） | 07（开始装货） |
| `unload_done` | 卸货完成 | 07（卸货中） | 06（待出门） | 06（卸货完成） |
| `load_done` | 装货完成 | 08（装货中） | 06（待出门） | 08（装货完成） |

#### 执行逻辑

```
1. 查主表当前 visitorstatus
2. 校验当前状态 == 动作要求的前置状态
3. 获取平台字段（tenant_id, form_id）
4. INSERT 流水记录到 tms_vehicle_realtime_record
5. UPDATE 主表 tms_visitor_appointment 的 visitorstatus
```

---

## 五、数据库核心表

### 5.1 tms_visitor_appointment（预约主表）

| 字段 | 类型 | 说明 |
|------|------|------|
| freservationno | varchar | 预约编号（主要业务键） |
| fmobile | varchar | 司机手机号 |
| visitorphone | varchar | 访客手机号 |
| fplatenumber | varchar | 车牌号 |
| visitorstatus | varchar | 当前状态，JSON数组格式 `["02"]` |
| fapplytype | varchar | 预约类型，JSON数组格式 |
| fvisitortype | varchar | 访客类型，JSON数组格式（01=访客, 02=送货, 03=提货） |
| fvehiclesize | varchar | 车辆尺寸，JSON数组格式 |
| fparkid | varchar | 园区ID |
| fparkid_fname | varchar | 园区ID（用于关联查询名称） |
| freservationtime | datetime | 预约时间 |
| fdrivername | varchar | 司机姓名 |
| visitorname | varchar | 访客姓名 |
| qrcode / qrcode_str | varchar | 二维码 |
| tenant_id / form_id | varchar | aPaaS平台字段 |

### 5.2 tms_vehicle_realtime_record（车辆状态流水表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | varchar | 主键（雪花ID） |
| freservationno | varchar | 预约编号（关联主表） |
| fvehiclestatus | varchar | 车辆状态，JSON数组格式 `["02"]` |
| ftime | datetime | 状态变更时间 |
| document_id / tab_doc_id | varchar | aPaaS文档ID |
| tenant_id / form_id | varchar | aPaaS平台字段 |
| status | varchar | 记录状态 |

### 5.3 其他表

| 表名 | 说明 |
|------|------|
| tms_park_management | 园区管理（fparkname 园区名称） |
| apaas_data_dictionary | 数据字典主表（dictionary_code） |
| apaas_data_dictionary_value | 数据字典值表（value_code → value_name） |
| jc_erp_sync_log | 同步操作日志 |

### 5.4 完整状态流转图

```
送货流程（fvisitortype=02）：
  提交预约(00) → 已预约(01) → 已签到(02) → 已叫号(03) → 已入厂(04) → 开始卸货(05) → 卸货完成(06) → 已出厂(09)

提货流程（fvisitortype=03）：
  提交预约(00) → 已预约(01) → 已签到(02) → 已叫号(03) → 已入厂(04) → 开始装货(07) → 装货完成(08) → 已出厂(09)

主表状态对照（visitorstatus / clcurstatus）：
  01=预约中  02=待签到  03=待入门  04=待卸货  05=待装货  06=待出门  07=卸货中  08=装货中
```

---

## 六、关键配置说明

### 6.1 application.properties 重要配置

```properties
# 服务端口
server.port=9092

# MySQL 数据源（CommDao 直接使用）
spring.datasource.url=jdbc:mysql://10.2.92.51:32306/xdap_app_787327234640707585?...
spring.datasource.username=787327234640707585app
spring.datasource.password=787327234640707585applJ7XHi#x

# aPaaS 平台租户
apaas.single.tenantId=787327234640707585
apaas.single.appId=789074181500174336

# 微信小程序
wx.appid=wx4145766f5eabd715
wx.secret=dd0bbca475c0667a24e5daa162653d35

# Redis
spring.redis.host=10.2.92.51
spring.redis.port=32379
spring.redis.password=xdapredis
```

### 6.2 URL白名单配置

新增的接口路径必须在 `TmsUrlAllowConfig` 中注册，否则会被 aPaaS 平台拦截：

```java
// 位置: com.xdap.tms.config.TmsUrlAllowConfig
@Component
public class TmsUrlAllowConfig implements AllowUrlManage {
    @Override
    public Set<String> getCustomAllowUrls() {
        Set<String> urlSet = new HashSet<>();
        urlSet.add("/custom/tms/appointment/*");
        // 新模块需要在这里添加：
        // urlSet.add("/custom/tms/新模块名/*");
        return urlSet;
    }
}
```

---

## 七、从0到1：新增业务接口完整流程

以下以新增一个"车辆管理"模块为例，演示完整开发步骤。

### Step 1: 创建包结构

在 `apaas-tms-service/src/main/java/com/xdap/tms/` 下创建：

```
vehicle/
├── controller/
│   └── VehicleController.java
├── model/
│   ├── VehicleQueryRequest.java
│   └── VehicleQueryResponse.java
└── service/
    └── VehicleService.java
```

### Step 2: 定义 Request 模型

```java
package com.xdap.tms.vehicle.model;

import lombok.Data;

@Data
public class VehicleQueryRequest {
    /** 微信登录code（如果是小程序接口则需要） */
    private String code;
    /** 车牌号 */
    private String plateNumber;
    /** 页码 */
    private Integer pageNo;
    /** 每页条数 */
    private Integer pageSize;
}
```

### Step 3: 定义 Response 模型

```java
package com.xdap.tms.vehicle.model;

import lombok.Data;
import java.util.List;

@Data
public class VehicleQueryResponse {
    private int total;
    private int pageNo;
    private int pageSize;
    private List<VehicleItem> list;

    @Data
    public static class VehicleItem {
        private String plateNumber;
        private String driverName;
        private String vehicleSize;
        private String status;
    }
}
```

### Step 4: 实现 Service

```java
package com.xdap.tms.vehicle.service;

import com.xdap.tms.dao.CommDao;
import com.xdap.tms.vehicle.model.VehicleQueryResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
@Slf4j
public class VehicleService {

    @Autowired
    private CommDao commDao;

    public VehicleQueryResponse queryVehicles(String plateNumber, int pageNo, int pageSize) {
        // 1. 查总数
        String countSql = "SELECT COUNT(1) as cnt FROM tms_visitor_appointment WHERE fplatenumber LIKE :plate";
        Map<String, Object> params = new HashMap<>();
        params.put("plate", "%" + plateNumber + "%");

        List<Map<String, Object>> countResult = commDao.queryForList(countSql, params);
        int total = 0;
        if (countResult != null && !countResult.isEmpty()) {
            total = ((Number) countResult.get(0).get("cnt")).intValue();
        }

        // 2. 分页查询
        VehicleQueryResponse response = new VehicleQueryResponse();
        response.setTotal(total);
        response.setPageNo(pageNo);
        response.setPageSize(pageSize);

        if (total == 0) {
            response.setList(new ArrayList<>());
            return response;
        }

        int offset = (pageNo - 1) * pageSize;
        String sql = "SELECT fplatenumber, fdrivername, fvehiclesize, visitorstatus " +
                "FROM tms_visitor_appointment WHERE fplatenumber LIKE :plate " +
                "ORDER BY freservationno DESC LIMIT :limit OFFSET :offset";
        params.put("limit", pageSize);
        params.put("offset", offset);

        List<Map<String, Object>> rows = commDao.queryForList(sql, params);
        List<VehicleQueryResponse.VehicleItem> items = new ArrayList<>();
        if (rows != null) {
            for (Map<String, Object> row : rows) {
                VehicleQueryResponse.VehicleItem item = new VehicleQueryResponse.VehicleItem();
                item.setPlateNumber(Objects.toString(row.get("fplatenumber"), null));
                item.setDriverName(Objects.toString(row.get("fdrivername"), null));
                // ...其他字段转换
                items.add(item);
            }
        }
        response.setList(items);
        return response;
    }
}
```

### Step 5: 实现 Controller

```java
package com.xdap.tms.vehicle.controller;

import com.definesys.mpaas.common.http.Response;
import com.xdap.tms.vehicle.model.VehicleQueryRequest;
import com.xdap.tms.vehicle.model.VehicleQueryResponse;
import com.xdap.tms.vehicle.service.VehicleService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/custom/tms/vehicle")
@Slf4j
public class VehicleController {

    @Autowired
    private VehicleService vehicleService;

    @PostMapping("/query")
    public Response query(@RequestBody VehicleQueryRequest request) {
        String plateNumber = request.getPlateNumber();
        if (plateNumber == null || plateNumber.trim().isEmpty()) {
            return Response.error("车牌号不能为空");
        }

        int pageNo = request.getPageNo() != null ? request.getPageNo() : 1;
        int pageSize = request.getPageSize() != null ? request.getPageSize() : 10;

        try {
            VehicleQueryResponse data = vehicleService.queryVehicles(plateNumber.trim(), pageNo, pageSize);
            return Response.ok().setData(data);
        } catch (Exception e) {
            log.error("车辆查询失败，车牌号: {}", plateNumber, e);
            return Response.error("查询失败: " + e.getMessage());
        }
    }
}
```

### Step 6: 注册URL白名单

编辑 `TmsUrlAllowConfig.java`，添加新模块路径：

```java
@Override
public Set<String> getCustomAllowUrls() {
    Set<String> urlSet = new HashSet<>();
    urlSet.add("/custom/tms/appointment/*");
    urlSet.add("/custom/tms/vehicle/*");    // ← 新增
    return urlSet;
}
```

### Step 7: 构建和部署

```bash
# 在项目根目录执行
mvn clean package -DskipTests

# 生成的可执行jar在：
# apaas-app/target/apaas-app-*.jar
```

---

## 八、开发规范速查

### 8.1 编码规范

| 规范项 | 约定 |
|--------|------|
| URL前缀 | `/custom/tms/{模块名}/` |
| HTTP方法 | 全部使用 **POST** |
| 内容类型 | `application/json` |
| 响应格式 | 统一使用 `Response.ok().setData(data)` / `Response.error(msg)` |
| Model注解 | 使用 Lombok `@Data` |
| Service注解 | `@Service` + `@Slf4j` |
| Controller注解 | `@RestController` + `@RequestMapping` + `@Slf4j` |
| DAO | 不单独建DAO，直接注入 `CommDao` |
| ID生成 | `SnowflakeIdGenerator.generateIdStr()` |

### 8.2 Controller 标准模板

```java
@PostMapping("/xxx")
public Response xxx(@RequestBody XxxRequest request) {
    // 1. 参数校验
    if (request.getField() == null || request.getField().trim().isEmpty()) {
        return Response.error("field不能为空");
    }

    // 2. 鉴权（如果是微信小程序接口）
    // if (!wxAuthService.validateCode(request.getCode())) {
    //     return Response.error("微信登录鉴权失败");
    // }

    // 3. 调用Service
    try {
        Object data = xxxService.doSomething(request);
        return Response.ok().setData(data);
    } catch (Exception e) {
        log.error("操作失败", e);
        return Response.error("操作失败: " + e.getMessage());
    }
}
```

### 8.3 Service 中常用工具方法

```java
// 从查询结果Map中安全取值
private String getStringValue(Map<String, Object> map, String key) {
    Object val = map.get(key);
    return val != null ? val.toString() : null;
}

// 格式化日期
private String formatDate(Object dateObj) {
    if (dateObj == null) return null;
    if (dateObj instanceof Date) {
        return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss").format((Date) dateObj);
    }
    return dateObj.toString();
}

// 解析JSON数组字段 ["01"] → "01"
private String parseJsonArrayValue(String value) {
    if (value == null) return null;
    value = value.trim();
    if (value.startsWith("[") && value.endsWith("]")) {
        String inner = value.substring(1, value.length() - 1).trim();
        if (inner.startsWith("\"") && inner.endsWith("\"")) {
            return inner.substring(1, inner.length() - 1);
        }
        return inner;
    }
    return value;
}

// 数据字典翻译
private String lookupDictValue(String dictCode, String valueCode) {
    if (dictCode == null || valueCode == null) return null;
    String sql = "SELECT v.value_name FROM apaas_data_dictionary d " +
            "INNER JOIN apaas_data_dictionary_value v ON d.id = v.dictionary_id " +
            "WHERE d.dictionary_code = :dictCode AND v.value_code = :valueCode LIMIT 1";
    Map<String, Object> params = new HashMap<>();
    params.put("dictCode", dictCode);
    params.put("valueCode", valueCode);
    List<Map<String, Object>> list = commDao.queryForList(sql, params);
    if (list != null && !list.isEmpty()) {
        return Objects.toString(list.get(0).get("value_name"), null);
    }
    return null;
}
```

### 8.4 需要微信鉴权的接口模板

```java
// Controller 中注入
@Autowired
private WxAuthService wxAuthService;

// 在接口方法中先做鉴权
String code = request.getCode();
if (code == null || code.trim().isEmpty()) {
    return Response.error("微信登录code不能为空");
}
if (!wxAuthService.validateCode(code.trim())) {
    return Response.error("微信登录鉴权失败");
}

// 解密手机号（如需要）
String fmobile = wxAuthService.decryptPhoneNumber(request.getPhoneCode());
```

---

## 九、Maven 依赖说明

### 根POM主要依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| spring-boot-starter-web | 2.2.7 | Web框架 |
| query-mongodb | apaas-1.1.11.bigdata.2 | aPaaS核心SDK（含MpaasQuery） |
| mysql-connector-java | 8.0.22 | MySQL驱动 |
| lombok | - | 简化POJO |
| fastjson | 1.2.47 | JSON处理 |
| commons-lang3 | 3.10 | 工具类 |
| aliyun-sdk-oss | 3.8.0 | 阿里云OSS文件存储 |

### 私有Maven仓库

```xml
<repositories>
    <repository>
        <id>dcloud-public</id>
        <url>https://registry.dfy.definesys.cn/repository/maven-public/</url>
    </repository>
</repositories>
```

---

## 十、Checklist：新增接口自查清单

- [ ] 在 `apaas-tms-service` 模块下创建 `{模块}/controller`、`{模块}/model`、`{模块}/service` 包
- [ ] Request/Response 模型使用 `@Data` 注解
- [ ] Service 注入 `CommDao`，使用原生SQL查询
- [ ] SQL 参数使用 `:paramName` 命名参数
- [ ] Controller 路由前缀为 `/custom/tms/{模块名}/`
- [ ] Controller 方法使用 `@PostMapping`
- [ ] 返回值统一使用 `Response.ok().setData()` / `Response.error()`
- [ ] Controller 中做参数校验和 try-catch
- [ ] 如果是微信小程序接口，加入 `WxAuthService` 鉴权
- [ ] 在 `TmsUrlAllowConfig` 中注册新的URL路径
- [ ] JSON数组字段（如 `visitorstatus`）读写时注意格式转换
- [ ] 需要编码翻译的字段通过数据字典查询

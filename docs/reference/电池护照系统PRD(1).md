电池护照系统
产品需求文档（PRD）

| 项目名称 | Ampace电池护照系统 |
| --- | --- |
| 实施方 | 得帆信息技术（上海）有限公司 |
| 编写人 | 宫彦秋 |
| 文档版本 | V2.2 |
| 编写日期 | 2026年4月3日 |

# 1. 项目概述

## 1.1 项目背景

根据欧盟电池法规要求，厦门新能安科技有限公司需要建立电池护照系统，用于管理和追溯电池全生命周期数据。该系统将基于得帆 aPaaS 低代码平台实施，实现电池护照数据的创建、管理、发布和查询功能。
## 1.2 文档目的

本文档旨在明确电池护照系统三个核心菜单（基础模版管理、项目模版管理、电池护照菜单）的产品需求，为系统设计和开发提供详细依据。
## 1.3 术语说明

| 术语 | 说明 |
| --- | --- |
| 基础模版 | 基于欧盟电池法规生成的标准数据模板，包含电池护照所需的标准字段结构 |
| 项目模版 | 基于基础模版创建，结合具体项目信息定制的模板 |
| 电池护照 | 面向最终用户展示的电池全生命周期数据，分为静态数据和动态数据 |
| 二维码 | 护照发布时生成的二维码，用于扫码查询电池护照信息 |
| 数据中台 | 核心数据源系统，按天同步数据 |
| 用户注册登陆体系 | 可自行注册、登陆、修改密码 |

# 2. 系统整体流程

## 2.1 业务主流程

系统整体业务流程如下：
基础模版 → 项目模版（两级审批）→ 项目启用（数据中台同步）→ 批量发布（首件校验）→ 电池护照数据 → 二维码生成
关键控制逻辑：
- 项目模版审批通过后，项目状态默认为「启用」，数据中台开始按天同步该项目的电池护照数据
- 项目状态设为「终止」时，数据中台停止同步；已有待发布数据保持待发布，可执行单条发布
- 项目模版子表中，字段同步状态为「禁止」的字段不从数据中台同步，且在电池护照展示页隐藏

图 2-1 电池护照系统业务流程图
## 2.2 系统集成

| 系统 | 集成说明 |
| --- | --- |
| 数据中台 | 核心数据源，项目发布时拉取触发；项目编码 → 成品料号 → SN序列；受项目状态及字段同步状态控制 |
| PLM系统 | 获取项目信息（项目编码、项目经理、项目名称、成品物料号） |
| 附件系统 | 通过成品料号获取产品相关附件信息，项目发布时拉取触发 |
| 碳足迹系统 | 通过成品料号获取碳足迹数据，项目发布时拉取触发 |
| 云系统 | 获取电池动态数据（19项），护照详情页展示时触发 |
| 二维码中间服务系统 | 接收护照URL与SN的映射关系，护照发布后推送 |
| MES系统 | 二维码生成对接（方向待确认） |
| 用户注册登陆体系 | 外部用户注册/登陆/修改密码，含管理员审批流程 |

## 2.3 接口清单

### 外部系统接口

| # | 系统 | 接口说明 | 触发时机 |
| --- | --- | --- | --- |
| 1 | 数据中台 | 根据成品料号/项目编码获取静态字段数据（电池标识、材料成分、原材料与供应链、废弃物与回收、性能与耐久静态数据、安全与标签、备件信息、电池状态等约100+项） | 项目发布时拉取触发 |
| 2 | PLM系统 | 查询项目信息（项目编码、项目名称、项目经理、成品物料号） | 新建项目模版时选择项目 |
| 3 | 附件系统 | 根据成品料号获取附件文件（欧盟符合性声明、CE标识、Article 6/7/8/10/12/14各报告、拆解手册、安全措施等） | 项目发布时拉取触发 |
| 4 | 碳足迹系统 | 根据成品料号获取碳足迹数据（单位功能单元碳足迹、各阶段贡献比、性能等级、绝对碳足迹等8项） | 项目发布时拉取触发 |
| 5 | 云系统 | 获取电池动态数据（剩余容量、SoC、充放电次数、温度信息等19项动态字段） | 护照详情页展示时触发（实时或按频率同步，待确认） |
| 6 | 二维码mes | 固定URL与SN映射关系，由中间服务生成二维码 | 护照发布后 |
| 7 | MES系统 | 二维码生成对接（方向待确认：MES回调通知 or 我方查询） | 待确认 |

### 内部系统接口

| # | 接口 | 说明 | 触发时机 |
| --- | --- | --- | --- |
| 1 | 单次发布校验 | 校验单条护照数据完整性 | 单条护照发布前 |
| 2 | 全量发布 | 批量发布项目下所有待发布护照数据 | 批量发布操作 |
| 3 | 外部用户注册审批（通过/拒绝） | 管理员审核注册申请，通过后触发邮件通知账号激活 | 管理员操作审批 |
| 4 | 护照详情查询 | 根据SN查询对应唯一一条护照数据 | 扫码后跳转 |
| 5 | 开放查询电池静态数据接口 | 开放给第三方客户查询电池护照，根据SN方式查询 | 根据PN查询所有 |
| 6 | 实时查询动态数据接口 | 针对SN查询阿里云静态数据接口 | 扫码展示SN信息时查询 |

# 3. 菜单一：基础模版管理

## 3.1 功能概述

基础模版是基于欧盟电池法规生成的标准数据模板，当前仅有一个基础模版。支持复制新建，支持删除，不需要审批流程。
## 3.2 页面字段

主表信息

| 字段名称 | 说明 |
| --- | --- |
| 模版编码 | 基础模版唯一值，系统自动生成 |
| 模版名称 | 基础模版显示名称 |
| 模版状态 | 启用 / 停用 |
| 创建人 | 负责人 |
| 创建时间 | 系统自动记录 |
| 更新时间 | 最近一次修改时间，系统自动记录 |
| 版本号 | 模版版本标识，修改后自动递增 |

子表信息

| 字段名称 | 说明 |
| --- | --- |
| 字段编码 | 字段唯一标识 |
| 字段名称 | 字段显示名称 |
| 字段内容 | 字段示例值或说明 |

## 3.3 功能需求

### 3.3.1 查看基础模版

- 展示基础模版列表，包含字段编码、字段名称、字段内容
### 3.3.2 新建基础模版

- 支持基于现有基础模版复制新建
- 复制后可修改字段内容
### 3.3.3 编辑基础模版

- 支持修改字段内容
### 3.3.4 删除基础模版

- 支持删除基础模版
### 3.3.5 审批流程

- 基础模版不需要审批流程
## 3.4 页面原型

📎 待补充：基础模版管理页面原型（列表页、新建/编辑弹窗、详情页）
## 3.5 权限说明

| 角色 | 权限 |
| --- | --- |
| 模板管理员 | 新建、编辑、删除基础模版 |
| 其他角色 | 只读 |

# 4. 菜单二：项目模版管理

## 4.1 功能概述

项目模版基于基础模版创建，结合具体项目信息进行定制。创建后需经过两级审批方可生效。
## 4.2 页面字段

主表信息

| 字段名称 | 示例值 | 数据来源 |
| --- | --- | --- |
| 项目编码 | code001 | PLM系统 |
| 项目名称 | 欧洲项目 | PLM系统 |
| 项目经理 | - | PLM系统 |
| 成品物料号 | code | 数据选择PLM系统的料号编码 |
| 基础模版 | 模版信息 | 数据选择 |
| 提交人 | - | 系统自动 |
| 创建时间 | - | 系统自动 |
| 所属部门 | - | 系统自动 |
| 是否推送URL | 是 / 否 | 手动选择，默认「否」 |
| 项目状态 | 启用 / 终止 | 手动操作，默认「启用」 |
| 电池保修期 | - | 手动填写 |
| 制造商标识符 | - | 手动填写 |
| 制造商名称 | - | 手动填写 |
| 制造商商标 | - | 手动填写 |
| 制造商网址 | - | 手动填写 |
| 制造商邮箱 | - | 手动填写 |
| 运营商标识符 | - | 手动填写 |
| 运营商名称 | - | 手动填写 |
| 运营商商标 | - | 手动填写 |
| 运营商联系地址 | - | 手动填写 |
| 运营商类型 | - | 手动填写 |
| 运营商网址 | - | 手动填写 |
| 运营商邮箱 | - | 手动填写 |
| 进口商标识符 | - | 手动填写 |
| 进口商名称 | - | 手动填写 |
| 进口商商标 | - | 手动填写 |
| 进口商联系地址 | - | 手动填写 |
| 进口商网址 | - | 手动填写 |
| 进口商邮箱 | - | 手动填写 |
| 碳足迹结果 | 附件 | ？？？ |

说明：制造商、运营商、进口商、电池保修期、碳足迹结果字段在项目模版中统一维护一次，自动覆盖该项目下所有电池护照数据。

子表信息

| 字段名称 | 示例值 | 数据来源 | 同步状态 |
| --- | --- | --- | --- |
| 字段编码 | - | 基础模版 | - |
| 字段名称 | - | 基础模版 | - |
| 字段内容 | - | 可定制修改 | - |
| 同步状态 | 启动 / 禁止 | 手动操作，默认「启动」 | - |

说明：子表字段不允许删除或修改内容，仅允许切换「同步状态」。设为「禁止」的字段不从数据中台同步，且在电池护照展示页直接隐藏。
## 4.3 数据关联逻辑

电池护照以成品料号作为唯一标识，数据流转分为三个阶段：
第一阶段：数据获取（3个系统）
成品料号 → 数据中台获取 SN 序列及成品料号信息
成品料号 → 附件系统获取附件信息 → 更新电池护照电池所有SN
成品料号 → 碳足迹系统获取碳足迹数据 → 更新电池护照电池所有SN
第二阶段：数据入库
将 SN 序列、成品料号、附件信息、碳足迹数据汇总后，写入电池护照数据表，并为每条护照记录生成对应的访问 URL
第三阶段：URL 分发（受「是否推送URL」字段控制）
- 项目模版中「是否推送URL」为「是」时，直接按 SN 匹配护照 URL，推送至二维码中间服务系统，生成二维码
- 「是否推送URL」为「否」时，先将数据推送给客户（客户数据推送），完成后同样汇入「按SN匹配护照URL」节点，继续推送至二维码中间服务生成二维码

图 4-1 电池护照数据关联流程
## 4.4 功能需求

### 4.4.1 新建项目模版

- 选择基础模版作为基础
- 从 PLM 系统选择项目（自动带入项目编码、项目名称、项目经理、成品物料号）
- 填写所属部门、提交人等信息
- 手动维护制造商、运营商、进口商基础信息及电池保修期（覆盖项目下所有电池护照）
- 可对子表字段内容进行定制修改，并按需设置各字段同步状态（启动/禁止）
- 审批通过后项目状态默认「启用」，数据中台每日按项目所需字段更新电池护照数据表
### 4.4.2 审批流程

| 节点 | 审批人 | 不通过处理 |
| --- | --- | --- |
| 第一审批节点 | 上级领导 | 退回修改 |
| 第二审批节点 | 待定 | 退回修改 |

审批不通过后，提交人修改后重新提交。
### 4.4.3 编辑项目模版

- 审批通过前可编辑
- 审批通过后如需修改，需重新发起审批
### 4.4.4 删除项目模版

- 支持删除未发布的项目模版
### 4.4.5 终止/启用项目

- 项目负责人或模板管理员可手动将项目状态切换为「终止」或「启用」
- 终止：数据中台停止同步该项目数据；已有待发布的电池护照数据保持「待发布」状态，可继续执行单条发布；全量发布后变为「已发布」
- 启用：恢复数据中台同步，按正常逻辑继续执行
- 操作权限：项目负责人、模板管理员
## 4.5 页面原型

📎 待补充：项目模版管理页面原型（列表页、新建表单、审批流程页、详情页）
## 4.6 权限说明

| 角色 | 权限 |
| --- | --- |
| 项目负责人 | 新建、编辑项目模版；终止/启用项目 |
| 审批人员 | 审批项目模版 |
| 模板管理员 | 管理所有项目模版；终止/启用项目 |

# 5. 菜单三：电池护照菜单

## 5.1 功能概述

电池护照菜单展示电池护照的完整数据。数据库层面为一张表，共 152 个字段；表单设计时按欧盟电池法规 SPEC 99100 标准进行分组展示（7个分组）。支持按项目筛选、发布状态筛选，支持首件校验和批量发布。
## 5.2 主字段

| 字段名称 | 说明 |
| --- | --- |
| 项目编码 | 筛选条件 |
| 项目名称 | 展示字段 |
| 项目经理 | 展示字段 |
| 发布状态 | 已发布 / 待发布 |
| 成品物料编码 | 只读 |

## 5.3 电池护照字段清单（152项）

说明：以下字段在数据库中为同一张表，按欧盟电池法规 SPEC 99100 七大标准分组展示。组件类型：输入框、数字、附件、链接、日期、时间。「项目模版统一维护」字段自动覆盖该项目下所有电池护照；「碳足迹核算」字段来自碳足迹核算系统；其余字段来自「数据中台」或「附件系统」。
### 6.1 标识符和产品数据（29项）

### 6.1.1 电池标识与生产信息（10项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 电池护照标识符 | Battery identifier | varchar | 数字 | 数据中台 | 欧盟注册平台 | 静态 |
| 生产日期 | Manufacturing date [YYYY-MM] | date | 日期 | 数据中台 | MES | 静态 |
| 生产地点 | Manufacturing place | varchar | 数字 | 数据中台 | SAP | 静态 |
| 电池类别(range值) | - | varchar | 输入框 | 数据中台 | PLM | 静态 |
| 电池类别 | Battery category | varchar | 输入框 | 数据中台 | PLM | 静态 |
| 电池重量 | Battery mass | decimal | 数字 | 数据中台 | PLM | 静态 |
| 电池模组重量 | Module mass | decimal | 数字 | 数据中台 | PLM | 静态 |
| 电芯重量 | Cell mass | decimal | 数字 | 数据中台 | PLM | 静态 |
| 电池保修期 | Warranty period of the battery [YYYY-MM] | date | 日期 | 项目模版统一维护 | PLM | 静态 |
| 电池投入使用日期 | Date of putting the battery into service [YYYY-MM] | date | 日期 | 数据中台 | 待确认 | 静态 |

### 6.1.2 制造商信息（6项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 制造商标识符 | Manufacturer identifier and information | varchar | 输入框 | 项目模版统一维护 | WMS | 静态 |
| 制造商名称 | Manufacturer name | varchar | 输入框 | 项目模版统一维护 | WMS | 静态 |
| 制造商商标 | Manufacturer registered trade name or registered trademark | varchar | 附件 | 项目模版统一维护 | WMS | 静态 |
| 制造商联系地址 | Manufacturer postal address, indicating a single contact point | varchar | 输入框 | 项目模版统一维护 | WMS | 静态 |
| 制造商网址（如有） | Manufacturer web address(if available) | varchar | 链接 | 项目模版统一维护 | WMS | 静态 |
| 制造商邮箱（如有） | Manufacturer e-mail address(if available) | varchar | 输入框 | 项目模版统一维护 | WMS | 静态 |

### 6.1.3 进口商信息（6项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 进口商标识符 | Importer identifier | varchar | 输入框 | 项目模版统一维护 | WMS | 静态 |
| 进口商名称 | Importer name | varchar | 输入框 | 项目模版统一维护 | WMS | 静态 |
| 进口商商标 | Importer registered trade name or registered trademark | varchar | 附件 | 项目模版统一维护 | WMS | 静态 |
| 进口商联系地址 | Importer postal address, indicating a single contact point | varchar | 输入框 | 项目模版统一维护 | WMS | 静态 |
| 进口商网址（如有） | Importer web address(if available) | varchar | 链接 | 项目模版统一维护 | WMS | 静态 |
| 进口商邮箱（如有） | Importer e-mail address(if available) | varchar | 输入框 | 项目模版统一维护 | WMS | 静态 |

### 6.1.4 运营商信息（6项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 运营商标识符 | Operator identifier | varchar | 输入框 | 项目模版统一维护 | PLM | 静态 |
| 运营商名称 | Operator name | varchar | 输入框 | 项目模版统一维护 | PLM | 静态 |
| 运营商商标 | Operator registered trade name or registered trademark | varchar | 附件 | 项目模版统一维护 | PLM | 静态 |
| 运营商联系地址 | Operator postal address, indicating a single contact point | varchar | 输入框 | 项目模版统一维护 | PLM | 静态 |
| 运营商网址（如有） | Operator web address(if available) | varchar | 链接 | 项目模版统一维护 | PLM | 静态 |
| 运营商邮箱（如有） | Operator e-mail address(if available) | varchar | 输入框 | 项目模版统一维护 | PLM | 静态 |

### 6.1.5 电池状态（1项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 电池状态 | Battery status | varchar | 输入框 | 数据中台 | 云枢 | 静态 |

### 6.2 符号、标签和符合性文件（12项）

### 6.2.1 符号与标签（4项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 分类回收标识 | Separate collection symbol | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| 镉和铅的符号 | Symbols for cadmium and lead | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| 灭火剂信息 | Extinguishing agent | varchar | 输入框 | 数据中台 | PLM | 静态 |
| 标签和符号的含义 | Meaning of labels and symbols | varchar | 输入框 | 数据中台 | PLM | 静态 |

### 6.2.2 符合性文件（8项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 欧盟符合性声明 | EU declaration of conformity | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| CE 标识 | EU declaration of conformity | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| Article 6 物质限制报告 | Results of test reports proving compliance | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| Article 7 碳足迹报告 | Results of test reports proving compliance | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| Article 8 回收料报告 | Results of test reports proving compliance | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| Article 10 性能与耐久报告 | Results of test reports proving compliance | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| Article 12 固定式储能电池的安全报告 | Results of test reports proving compliance | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| Article 14 SOH和预期寿命报告 | Results of test reports proving compliance | varchar | 附件 | 附件系统 | PLM系统 | 静态 |

### 6.3 电池碳足迹（9项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 碳足迹结果 | Carbon footprint results | varchar | 附件 | 项目模版统一维护 | SRM/电池护照 | 静态 |
| 单位功能单元的电池碳足迹 | Battery Carbon Footprint per Functional Unit | decimal | 数字 | 碳足迹核算 | 待确认 | 静态 |
| 原材料获取和预处理阶段碳足迹贡献比 | Contribution of raw material acquisition and pre-processing | decimal | 数字 | 碳足迹核算 | 待确认 | 静态 |
| 生产/制造阶段碳足迹贡献比 | Contribution of main product production/manufacturing | decimal | 数字 | 碳足迹核算 | 待确认 | 静态 |
| 分销阶段碳足迹贡献比 | Contribution of distribution lifecycle stage | decimal | 数字 | 碳足迹核算 | 待确认 | 静态 |
| 报废和回收阶段碳足迹贡献比 | Contribution of end of life and recycling | decimal | 数字 | 碳足迹核算 | 待确认 | 静态 |
| 碳足迹性能等级 | Carbon footprint performance class | varchar | 输入框 | 碳足迹核算 | 待确认 | 静态 |
| 公开碳足迹研究的网络链接 | Web link to public carbon footprint study | varchar | 链接 | 碳足迹核算 | 待确认 | 静态 |
| 电池绝对碳足迹 | Absolute battery carbon footprint | decimal | 数字 | 碳足迹核算 | 待确认 | 静态 |

### 6.4 供应链尽职调查（3项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 尽职调查报告信息 | Information of due diligence report | varchar | 附件 | 附件系统 | 供应商管理 | 静态 |
| 认可体系的第三方保证 | Third-party assurances of recognised schemes | varchar | 附件 | 附件系统 | 供应商管理 | 静态 |
| 供应链指数 | Supply chain indices | varchar | 输入框 | 数据中台 | 供应商管理 | 静态 |

### 6.5 电池材料及成分（17项）

### 6.5.1 材料成分（8项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 电池化学体系(range值) | - | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 电池化学体系（枚举名称） | Battery chemistry | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 关键原材料 | Critical raw materials | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 正极材料 | Materials used in cathode, anode and electrolyte | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 负极材料 | Materials used in cathode, anode and electrolyte | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 电解液材料 | Materials used in cathode, anode and electrolyte | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 有害物质 | Hazardous substances | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 物质对环境、人类健康、安全及人员的影响 | Impact of substances on environment, human health, safety, persons | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |

### 6.5.2 原材料与供应链（9项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 模组原材料-物料编码 | Material code | varchar | 数字 | 数据中台 | SRM | 静态 |
| 单重 | Unit weight | decimal | 数字 | 数据中台 | SRM | 静态 |
| 材质组成 | Material composition | varchar | 数字 | 数据中台 | SRM | 静态 |
| 运输距离 | Transportation distance | decimal | 数字 | 数据中台 | SRM | 静态 |
| 运输方式 | Mode of transportation | varchar | 数字 | 数据中台 | SRM | 静态 |
| 是否为新能源运输 | Whether it is new energy transportation | decimal | 数字 | 数据中台 | SRM | 静态 |
| 供应商编码 | - | varchar | 输入框 | 数据中台 | SRM | 静态 |
| 电芯原材料-投入量 | Input quantity | decimal | 数字 | 数据中台 | MES | 静态 |
| 电芯原材料-报废量 | Scrap quantity | decimal | 数字 | 数据中台 | MES | 静态 |

### 6.6 循环性和资源效率（34项）

### 6.6.1 再生材料占比（10项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 消费前再生镍占比 | Pre-consumer recycled nickel share | decimal | 数字 | 数据中台 | SRM | 静态 |
| 消费前再生钴占比 | Pre-consumer recycled cobalt share | decimal | 数字 | 数据中台 | SRM | 静态 |
| 消费前再生锂占比 | Pre-consumer recycled lithium share | decimal | 数字 | 数据中台 | SRM | 静态 |
| 消费前再生铅占比 | Pre-consumer recycled lead share | decimal | 数字 | 数据中台 | SRM | 静态 |
| 消费后再生镍占比 | Post-consumer recycled nickel share | decimal | 数字 | 数据中台 | SRM | 静态 |
| 消费后再生钴占比 | Post-consumer recycled cobalt share | decimal | 数字 | 数据中台 | SRM | 静态 |
| 消费后再生锂占比 | Post-consumer recycled lithium share | decimal | 数字 | 数据中台 | SRM | 静态 |
| 消费后再生铅占比 | Post-consumer recycled lead share | decimal | 数字 | 数据中台 | SRM | 静态 |
| 可再生成分占比 | Renewable content share | decimal | 数字 | 数据中台 | SRM | 静态 |
| 消费前和消费后再生钴、锂、镍和铅的占比 | Pre/post-consumer recycled Co, Li, Ni, Pb share | decimal | 数字 | 数据中台 | SRM | 静态 |

### 6.6.2 废弃物与回收（14项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 固废产生量 | Solid waste generation volume | decimal | 数字 | 数据中台 | WMS | 静态 |
| 危废产生量 | Hazardous waste generation volume | decimal | 数字 | 数据中台 | 电池护照(excel导入) | 静态 |
| 单位产品固废产生量 | Solid waste generation per unit of product | decimal | 数字 | 数据中台 | WMS | 静态 |
| 单位产品危废产生量 | Hazardous waste generation per unit of product | decimal | 数字 | 数据中台 | WMS(计算得出) | 静态 |
| 废弃物运输方式 | Waste transportation method | varchar | 输入框 | 数据中台 | WMS(默认值) | 静态 |
| 下仓数 | - | varchar | 数字 | 数据中台 | WMS | 静态 |
| 物料编号 | - | varchar | 输入框 | 数据中台 | WMS | 静态 |
| 物料描述 | - | varchar | 输入框 | 数据中台 | WMS | 静态 |
| 收货数量 | - | varchar | 数字 | 数据中台 | WMS | 静态 |
| 重量 | - | varchar | 数字 | 数据中台 | WMS | 静态 |
| 日期 | - | varchar | 时间 | 数据中台 | WMS | 静态 |
| 成品编码 | - | varchar | 输入框 | 数据中台 | WMS | 静态 |
| 产出 | - | varchar | 输入框 | 数据中台 | WMS | 静态 |
| A产品碳足迹 | 阳极级片（SA-） | varchar | 输入框 | 数据中台 | WMS | 静态 |

### 6.6.3 拆解与二次利用（6项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 拆解信息：电池包拆卸和拆解手册 | Manuals for the removal and the disassembly of the battery pack | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| 零部件编号 | Part numbers for components | varchar | 链接 | 数据中台 | PLM系统 | 静态 |
| 安全措施 | Safety measures | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| 终端用户在废物预防中的作用相关信息 | Information on role of end-users in waste prevention | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| 终端用户在废电池分类收集中的作用相关信息 | Information on role of end-users in separate collection | varchar | 附件 | 附件系统 | PLM系统 | 静态 |
| 电池收集、二次利用准备及报废处理相关信息 | Information on battery collection, second life and end of life | varchar | 附件 | 附件系统 | PLM系统 | 静态 |

### 6.6.4 备件与维修（4项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 备件来源地址 | Postal address of sources for spare parts | varchar | 输入框 | 数据中台 | SAP | 静态 |
| 备件来源电子邮箱 | E-mail address of sources for spare parts | varchar | 输入框 | 数据中台 | SAP | 静态 |
| 备件来源网址 | Web address of sources for spare parts | varchar | 链接 | 数据中台 | SAP | 静态 |
| 维修信息 | Repair information | varchar | 输入框 | 数据中台 | 云枢 | 静态 |

### 6.7 性能和耐久性（48项）

### 6.7.1 静态数据（29项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 额定容量 | Rated capacity | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 容量衰减 | Capacity fade | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 认证可用电池能量 | Certified usable battery energy | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 最低电压 | Minimum voltage | varchar | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 最高电压 | Maximum voltage | varchar | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 额定电压 | Nominal voltage | varchar | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 初始功率性能 | Original power capability | varchar | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 80% SOC剩余功率性能 | Remaining power capability | varchar | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 20% SOC剩余功率性能 | - | varchar | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 功率衰减 | Power fade | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 电池允许最大功率 | Maximum permitted battery power | varchar | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 电池额定功率与电池能量的比值 | Ratio between nominal battery power and battery energy | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 初始往返能量效率 | Initial round trip energy efficiency | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 循环寿命50%时的往返能量效率 | Round trip energy efficiency at 50% of cycle-life | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 往返能量效率衰减 | Energy round trip efficiency fade | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 初始自放电率 | Initial self-discharge rate | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 电池包初始内阻 | Initial internal resistance of battery pack | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 电池模块初始内阻 | Initial internal resistance of battery module | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 电芯初始内阻 | Initial internal resistance of battery cell | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 电池包内阻增量 | Internal resistance increase of battery pack | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 电芯内阻增量 | Internal resistance increase of battery cell | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 电池模块内阻增量 | Internal resistance increase of battery module | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 预期日历寿命（年） | Expected lifetime in calendar years | decimal | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 预期寿命：充放电循环次数 | Expected lifetime: Number of charge-discharge cycles | decimal | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 循环寿命参考测试 | Cycle-life Reference test | decimal | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 相关循环寿命测试的倍率（C-rate） | C-rate of relevant cycle-life test | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 耗尽容量阈值 | Capacity threshold for exhaustion | decimal | 数字 | 数据中台 | 数据中台(PLM) | 静态 |
| 闲置状态温度范围（下限） | Temperature range idle state (lower boundary) | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |
| 闲置状态温度范围（上限） | Temperature range idle state (upper boundary) | varchar | 输入框 | 数据中台 | 数据中台(PLM) | 静态 |

### 6.7.2 动态数据（19项）

| 字段名称（中文） | 字段名称（英文） | 类型 | 组件 | 数据来源 | 附件来源 | 动静态 |
| --- | --- | --- | --- | --- | --- | --- |
| 剩余容量 | Remaining capacity | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 剩余可用电池能量 | Remaining usable battery energy | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 认证能量状态（SOCE） | State of certified energy (SOCE) | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 充电状态（SoC） | State of charge (SoC) | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 剩余功率性能（动态） | Remaining power capability (dynamic) | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 剩余往返能量效率 | Remaining round trip energy efficiency | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 当前自放电率 | Current self-discharge rate | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 自放电率变化情况 | Evolution of self-discharge rates | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 完全充放电循环次数 | Number of full charging and discharging cycles | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 能量吞吐量 | Energy throughput | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 容量吞吐量 | Capacity throughput | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 温度信息 | Temperature information | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 在边界以上极端温度下的持续时间 | Time spent in extreme temperatures above boundary | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 在边界以下极端温度下的持续时间 | Time spent in extreme temperatures below boundary | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 在极端高温下的充电时间 | Time spent charging during extreme temperatures above | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 在极端低温下的充电时间 | Time spent charging during extreme temperatures below | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 深度放电事件次数 | Number of deep discharge events | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 过充电事件次数 | Number of overcharge events | decimal | 数字 | 云系统 | 云系统 | 动态 |
| 事故相关信息 | Information on accidents | varchar | 输入框 | 云系统 | 云系统 | 动态 |

## 5.4 批量发布功能

首件校验
- 项目负责人手动选择一条数据进行审核
- 审核内容：核对静态数据完整性、动态数据合理性、字段权限级别正确性
- 审核通过后方可进行批量发布
- 审核不通过：标记问题字段，退回数据修正
批量发布
- 选择单一项目进行全量发布
- 发布前置校验：系统判断是否存在至少一条数据；校验首件是否已通过审核；校验必填字段是否完整
- 发布确认：弹出二次确认弹窗，展示本次发布的数据条数，确认后执行发布
- 全量发布后不允许删除
发布异常处理
- 发布过程中如部分数据校验失败，系统记录失败明细（SN、失败原因），成功数据正常发布
- 失败数据保持「待发布」状态，支持修正后重新发布
- 系统提供发布日志，记录每次发布的操作人、时间、成功/失败条数
二维码生成
- 护照发布时自动生成二维码
⚠ MES系统中电池未生产完成时无SN和静态数据，只有二维码生成后才有SN，需与生产部门进一步确认
## 5.5 二维码扫码预览

### 5.5.1 功能概述

MES 系统在电池生产完成后生成二维码，用户扫描二维码后跳转至电池护照系统，查看该电池对应的一条护照数据详情。
### 5.5.2 触发条件

- 电池护照状态为已发布，方可通过二维码访问
- 未发布的护照不对外提供扫码入口
### 5.5.3 扫码跳转逻辑

扫描二维码 → 用户认证（携带SN）→ 认证成功 → 直接展示对应SN护照详情
- 二维码携带电池 SN 信息，用户进入认证体系时 SN 随之传递
- 每个 SN 对应唯一一条电池护照数据
### 5.5.4 用户认证流程（携带SN）

用户扫码后进入用户注册登陆体系，所有认证操作均携带 SN：

| 操作 | 说明 |
| --- | --- |
| 注册 | 新用户填写注册信息 → 提交审批 → 审批通过后账号激活 → 登陆后跳转至对应SN护照详情页 |
| 登陆 | 已有账号（审批已通过）直接登陆，成功后自动跳转至对应SN护照详情页 |
| 修改密码 | 修改密码后重新登陆，SN保持传递，登陆成功后跳转护照详情页 |

注册审批说明：
- 注册提交后账号处于待审批状态，用户暂不可登陆
- 由内部管理员审核通过后账号激活，系统通知用户
- 审批不通过：系统通知用户补充材料或说明拒绝原因
- 审批通过后用户重新扫码或直接登陆，SN仍可正常携带跳转
认证成功后，系统根据访问者权限级别展示对应字段，无需用户再次搜索或输入SN。
### 5.5.5 护照详情页展示内容

- 根据访问者身份（内部用户 / 外部客户）及其权限级别，展示对应可见字段
- 字段权限分级参见第 6 章权限体系
### 5.5.6 待确认事项

⚠️ MES 系统中电池未生产完成时无 SN 和静态数据，只有二维码生成后才有 SN，需与生产部门进一步确认二维码与 SN 的生成时序
## 5.6 页面原型

📎 待补充：电池护照菜单页面原型（列表页、静态数据详情、动态数据详情、批量发布操作页、二维码扫码预览页）
## 5.7 权限说明

| 角色 | 权限 |
| --- | --- |
| 项目负责人 | 首件审核、批量发布、单条发布、删除（发布前） |
| 全部人员 | 根据权限级别查看电池护照数据 |

# 6. 权限体系

## 6.1 数据权限分级（字段级）

| 权限级别 | 字段数量 | 说明 |
| --- | --- | --- |
| Public | 82项 | 公开数据，所有人可读。包括电池标识、生产信息、碳足迹、性能参数等 |
| PLI | 32项 | 仅限对应产品线内部可见。包括电池状态、剩余容量、充电状态、温度信息等 |
| NB/MSA/EC | 6项 | 核心部门/业务敏感数据。包括物质限制报告、碳足迹报告、回收料报告等合规报告 |
| PLI+Commission | 9项 | 最高权限。包括正负极材料、电解液、拆解信息等 |
| 访客 | 部分数据 | 可查看部分数据 |

## 6.2 内部用户角色

| 角色 | 权限说明 |
| --- | --- |
| 系统管理员 | 系统配置和用户管理 |
| 模板管理员 | 基础模版和项目模版管理 |
| 项目负责人 | 项目模版创建、数据填报、首件审核、批量发布 |
| 全部人员 | 根据权限级别查看电池护照数据 |
| 审批人员 | 项目模版审批 |

## 6.3 外部客户注册

### 6.3.1 注册与审核流程

- 客户通过自研注册系统提交注册申请
- 注册信息：公司名称、联系人、联系方式、营业执照（可选）、申请访问的项目/产品范围
- 注册审核：由内部管理员审核通过后激活账号
- 审核不通过：系统通知客户补充材料或说明拒绝原因
### 6.3.2 权限分配

- 字段级权限控制：根据客户类型（终端客户、经销商、回收商、监管机构）分配不同的数据访问权限
- 权限由系统管理员在后台配置，支持按客户类型批量设置
- 客户仅可查看被授权项目下的电池护照数据
### 6.3.3 账号生命周期管理

- 账号有效期：支持设置账号有效期限，到期后自动停用
- 账号停用/注销：管理员可手动停用或注销外部客户账号
- 密码策略：支持忘记密码、修改密码
# 7. 非功能性需求

## 7.1 性能要求

| 指标 | 要求 |
| --- | --- |
| 列表页加载 | ≤ 3秒（1000条数据以内） |
| 批量发布 | 支持单次≥5000条数据发布，超时上限10分钟 |
| 二维码扫码响应 | ≤ 2秒返回护照详情页 |
| 并发用户数 | 支持≥50个内部用户同时在线操作 |

## 7.2 数据同步

| 项目 | 说明 |
| --- | --- |
| 同步频率 | 数据中台按天同步（建议每日凌晨02:00执行） |
| 同步方式 | 增量同步为主，支持手动触发全量同步 |

# 8. 待确认事项

以下事项需要进一步与客户确认：

| 序号 | 待确认事项 | 负责人 | 截止日期 |
| --- | --- | --- | --- |
| 1 | 基础模版创建部门和维护责任人 | 待定 | 待定 |
| 2 | 项目模版第二个审批节点的审批人/部门 | 待定 | 待定 |
| 3 | 各数据类别的负责部门和填报方式 | 待定 | 待定 |
| 4 | 数据校验规则、审核机制和异常处理流程 | 待定 | 待定 |
| 5 | 内部用户角色的详细权限定义 | 待定 | 待定 |
| 6 | MES系统中SN生成时机与二维码生成的协调机制 | 待定 | 待定 |
| 7 | 外部客户类型划分及对应权限级别 | 待定 | 待定 |
| 8 | 数据中台提供数据结构，最终电池护照数据需要明确多少 | 待定 | 待定 |
| 9 | 批量发布数据量上限及性能指标确认 | 待定 | 待定 |

# 9. 附录

## 9.1 相关文档

- 电池护照系统业务流程调研报告 V1.0
- 电池护照系统需求调研问卷（0316版本）
- 电池护照表数据.xlsx
- Ampace电池护照项目进度计划20260316.xlsx
## 9.2 版本历史

| 版本 | 日期 | 修改内容 | 修改人 |
| --- | --- | --- | --- |
| V1.0 | 2026-03-18 | 初稿，基于业务流程调研报告和数据字段清单编写 | 宫彦秋 |
| V2.0 | 2026-03-25 | 补充全篇逻辑关系以及全景逻辑图 | 宫彦秋 |
| V2.1 | 2026-03-31 | OA改为PLM；项目模版新增基础字段维护；新增项目终止/启用；新增字段同步状态控制 | 宫彦秋 |
| V2.2 | 2026-04-02 | 新增术语「用户注册登陆体系」；5.3碳足迹精简为9项，动态数据来源改为云系统；6.1新增访客权限；新增5.5.3/5.5.4扫码用户认证流程 | 宫彦秋 |
| V2.3 | 2026-04-07 | 5.3字段清单按欧盟电池法规SPEC 99100七大分组（6.1~6.7）重新归类，字段总数更新为152项 | 宫彦秋 |

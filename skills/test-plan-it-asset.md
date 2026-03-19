# 功能设计文档：IT 资产管理系统

## 应用概述

| 项目 | 值 |
|------|-----|
| 应用名称 | IT资产管理 |
| 应用编码 | it-asset |
| 应用描述 | 企业IT资产全生命周期管理，包括资产登记、领用、归还、报废 |
| 主题色 | 蓝色 `#027AFF` |

## 数据模型设计

### 模型 1：资产信息（asset_info）

| 字段名 | 编码 | 类型 | 说明 |
|--------|------|------|------|
| 资产编号 | asset_no | 单据号 | 自动生成 |
| 资产名称 | asset_name | 单行输入 | 必填 |
| 资产分类 | asset_category | 下拉单选 | 绑定字典 |
| 品牌型号 | brand_model | 单行输入 | |
| 购入日期 | purchase_date | 日期时间 | |
| 购入金额 | purchase_amount | 金额 | |
| 资产状态 | asset_status | 下拉单选 | 绑定字典 |
| 存放位置 | storage_location | 单行输入 | |
| 负责人 | responsible_person | 人员选择 | |
| 备注 | asset_remark | 多行输入 | |
| 资产照片 | asset_photo | 附件上传 | |

### 模型 2：领用记录（borrow_record）

| 字段名 | 编码 | 类型 | 说明 |
|--------|------|------|------|
| 领用单号 | borrow_no | 单据号 | 自动生成 |
| 关联资产 | related_asset | 数据单选 | 关联 asset_info，显示 asset_name |
| 领用人 | borrower | 人员选择 | 必填 |
| 领用日期 | borrow_date | 日期时间 | 必填 |
| 预计归还日期 | expected_return_date | 日期时间 | |
| 领用状态 | borrow_status | 下拉单选 | 绑定字典 |
| 领用说明 | borrow_remark | 多行输入 | |
| 是否已归还 | is_returned | 开关 | |

## 数据字典设计

### 字典 1：资产分类（asset_category）

| 选项名 | 编码 |
|--------|------|
| 笔记本电脑 | laptop |
| 台式电脑 | desktop |
| 显示器 | monitor |
| 打印机 | printer |
| 网络设备 | network |
| 服务器 | server |
| 其他 | other |

### 字典 2：资产状态（asset_status）

| 选项名 | 编码 |
|--------|------|
| 闲置 | idle |
| 使用中 | in_use |
| 维修中 | repairing |
| 已报废 | scrapped |

### 字典 3：领用状态（borrow_status）

| 选项名 | 编码 |
|--------|------|
| 待审批 | pending |
| 已批准 | approved |
| 已领用 | borrowed |
| 已归还 | returned |
| 已拒绝 | rejected |

## 角色设计

| 角色名称 | 编码 | 说明 |
|----------|------|------|
| 资产管理员 | asset_admin | 管理所有资产，审批领用申请 |
| 普通员工 | employee | 提交领用申请，查看自己的领用记录 |

## 表单设计

### 表单 1：资产信息

- **表单名称**：资产信息
- **绑定模型**：asset_info
- **组件列表**：全部 11 个字段
- **列表页查询条件**：资产编号、资产名称、资产分类、资产状态
- **列表页显示列**：资产编号、资产名称、资产分类、品牌型号、资产状态、负责人

### 表单 2：领用记录

- **表单名称**：领用记录
- **绑定模型**：borrow_record
- **组件列表**：全部 8 个字段
- **列表页查询条件**：领用单号、领用人、领用状态
- **列表页显示列**：领用单号、关联资产、领用人、领用日期、领用状态、是否已归还

## 涉及的组件类型覆盖

| 组件类型 | 使用位置 |
|---------|---------|
| FORM_DOCUMENT_NUMBER | 资产编号、领用单号 |
| FORM_TEXT_INPUT | 资产名称、品牌型号、存放位置 |
| FORM_TEXTAREA_INPUT | 备注、领用说明 |
| FORM_MONEY_INPUT | 购入金额 |
| FORM_DATEPICK_INPUT | 购入日期、领用日期、预计归还日期 |
| FORM_SELECT_INPUT_SINGLE | 资产分类、资产状态、领用状态 |
| FORM_DATA_SELECTOR_SINGLE | 关联资产 |
| FORM_PEOPLE_SELECT | 负责人、领用人 |
| FORM_FILE_UPLOAD | 资产照片 |
| FORM_SWITCH_SELECT | 是否已归还 |

**覆盖 10/16 个组件类型**（未使用：数字输入、手机号码、电子邮箱、下拉多选、地理位置、子表）

## Skills 执行计划

### Phase 1：创建应用
- `apaas-create-app` → 创建 "IT资产管理" 应用，获取 appId

### Phase 2：创建公共资源
- `apaas-create-dict` → 批量创建 3 个字典
- `apaas-create-role` → 创建 2 个角色

### Phase 3：创建数据模型
- `apaas-create-model` → 创建 asset_info 和 borrow_record 两个模型

### Phase 4：创建表单
- `apaas-create-form` → 创建 2 个表单（资产信息 + 领用记录）

### Phase 5：验证查询能力
- `apaas-query-model` → 查询已创建的模型和字段
- `apaas-query-dict` → 查询已创建的字典和选项
- `apaas-query-role` → 查询已创建的角色
- `apaas-query-form` → 查询菜单和表单详情

### Phase 6：验证更新能力
- `apaas-update-app` → 修改应用名称为 "IT资产管理系统"
- `apaas-update-dict` → 给"资产分类"字典追加一个选项 "移动设备"
- `apaas-update-role` → 修改"资产管理员"角色名称
- `apaas-update-form` → 修改"资产名称"字段为必填
- `apaas-add-field` → 给 asset_info 追加一个字段 "保修到期日"

### Phase 7：还原测试修改
- 将 Phase 6 的修改还原回去

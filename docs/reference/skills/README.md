# aPaaS Builder Skills

得帆云 aPaaS 平台原子能力 Skills 集合

## 平台基础操作 (14个)

| Skill | 说明 | API 端点 |
|-------|------|---------|
| [apaas-create-app](./apaas-create-app.md) | 创建应用 | POST /xdap-app/apaasApplications/addApp |
| [apaas-update-app](./apaas-update-app.md) | 修改应用信息 | GET queryAppById → POST saveApp |
| [apaas-create-model](./apaas-create-model.md) | 创建数据模型 | POST /xdap-app/common/resource/v2/appModel |
| [apaas-query-model](./apaas-query-model.md) | 查询模型及字段 | POST /xdap-app/dataModel/query/modelWithField |
| [apaas-add-field](./apaas-add-field.md) | 给已有模型追加字段 | POST /xdap-app/modelField/add |
| [apaas-create-dict](./apaas-create-dict.md) | 创建数据字典 | POST /xdap-app/common/resource/appDict |
| [apaas-query-dict](./apaas-query-dict.md) | 查询字典及选项 | POST /xdap-app/dataDictionary/query/dataDictionaryList |
| [apaas-update-dict](./apaas-update-dict.md) | 编辑字典及选项 | POST /xdap-app/dataDictionary/edit/dataDictionary |
| [apaas-create-role](./apaas-create-role.md) | 创建角色 | POST /xdap-app/common/resource/appRole |
| [apaas-query-role](./apaas-query-role.md) | 查询角色列表 | GET /xdap-app/user/select/queryRoleList |
| [apaas-update-role](./apaas-update-role.md) | 编辑/删除角色 | POST /xdap-app/roles/edit/role |
| [apaas-create-form](./apaas-create-form.md) | 创建表单配置 | POST /xdap-app/common/resource/formConfig |
| [apaas-query-form](./apaas-query-form.md) | 查询表单菜单及详情 | POST manageAppMenu → GET formContext |
| [apaas-update-form](./apaas-update-form.md) | 编辑表单配置 | POST /xdap-app/formConfig/save/formConfigDetail |

## 表单组件 Skills (16个)

### 基础输入组件

| Skill | 组件类型 | 字段类型 | 说明 |
|-------|---------|---------|------|
| [apaas-comp-text](./apaas-comp-text.md) | FORM_TEXT_INPUT | STRING | 单行输入 |
| [apaas-comp-textarea](./apaas-comp-textarea.md) | FORM_TEXTAREA_INPUT | BIG_TEXT | 多行输入 |
| [apaas-comp-number](./apaas-comp-number.md) | FORM_NUMBER_INPUT | NUM | 数字输入 |
| [apaas-comp-money](./apaas-comp-money.md) | FORM_MONEY_INPUT | NUM | 金额 |
| [apaas-comp-phone](./apaas-comp-phone.md) | FORM_PHONE_INPUT | STRING | 手机号码 |
| [apaas-comp-email](./apaas-comp-email.md) | FORM_EMAIL_INPUT | STRING | 电子邮箱 |
| [apaas-comp-date](./apaas-comp-date.md) | FORM_DATEPICK_INPUT | DATE | 日期时间 |
| [apaas-comp-doc-number](./apaas-comp-doc-number.md) | FORM_DOCUMENT_NUMBER | STRING | 单据号 |

### 选择器组件

| Skill | 组件类型 | 字段类型 | 说明 |
|-------|---------|---------|------|
| [apaas-comp-select-single](./apaas-comp-select-single.md) | FORM_SELECT_INPUT_SINGLE | STRING | 下拉单选（绑定字典） |
| [apaas-comp-select-multi](./apaas-comp-select-multi.md) | FORM_SELECT_INPUT | STRING | 下拉多选（绑定字典） |
| [apaas-comp-data-selector](./apaas-comp-data-selector.md) | FORM_DATA_SELECTOR_SINGLE | STRING | 数据单选（关联模型） |
| [apaas-comp-people](./apaas-comp-people.md) | FORM_PEOPLE_SELECT | STRING | 人员选择 |

### 其他组件

| Skill | 组件类型 | 字段类型 | 说明 |
|-------|---------|---------|------|
| [apaas-comp-file](./apaas-comp-file.md) | FORM_FILE_UPLOAD | STRING | 附件上传 |
| [apaas-comp-switch](./apaas-comp-switch.md) | FORM_SWITCH_SELECT | STRING | 开关 |
| [apaas-comp-location](./apaas-comp-location.md) | FORM_WIDGET_LOCATION | STRING | 地理位置 |
| [apaas-comp-son-table](./apaas-comp-son-table.md) | FORM_WIDGET_SON_TABLE | — | 子表 |

## 快速开始

### 1. 创建应用
```python
from app.apaas_client import APaaSClient

client = APaaSClient()
await client.login("account", "password")

app_data = await client.create_app("客户管理", "crm-system", "CRM应用")
app_id = str(app_data.get("id"))
```

### 2. 创建数据模型
```python
from app.config_transformer import transform_models

models = [
    {
        "name": "客户",
        "code": "customer",
        "fields": [
            {"name": "客户名称", "code": "customer_name", "type": "单行输入"},
            {"name": "联系电话", "code": "contact_phone", "type": "手机号码"}
        ]
    }
]

payload, code_map = transform_models(app_id, models)
model_results = await client.create_models(app_id, payload)
```

### 3. 创建数据字典
```python
from app.config_transformer import transform_dicts

dicts = [
    {
        "name": "客户等级",
        "code": "customer_level",
        "options": [
            {"name": "VIP", "code": "vip"},
            {"name": "普通", "code": "normal"}
        ]
    }
]

payload, dict_code_map = transform_dicts(app_id, dicts)
await client.create_dicts(app_id, payload)
```

### 4. 创建表单配置
```python
from app.config_transformer import transform_form_config

form_payload = transform_form_config(
    models, dicts, model_results, payload, code_map, dict_code_map
)
await client.create_form_config(app_id, form_payload)
```

## 使用场景

### 场景 1: 简单表单（文本 + 下拉）
使用 Skills:
- `apaas-create-app`
- `apaas-create-model`
- `apaas-create-dict`
- `apaas-create-form`
- `apaas-comp-text`
- `apaas-comp-select-single`

### 场景 2: 关联表单（外键关系）
使用 Skills:
- `apaas-create-app`
- `apaas-create-model` (创建多个模型)
- `apaas-create-form`
- `apaas-comp-text`
- `apaas-comp-data-selector`

### 场景 3: 主子表表单
使用 Skills:
- `apaas-create-app`
- `apaas-create-model` (自动创建主表和子表模型)
- `apaas-create-form`
- `apaas-comp-text`
- `apaas-comp-son-table`

### 场景 4: 在已有应用中扩展（新增模型 + 表单）
使用 Skills:
- `apaas-query-model` (查询已有模型，获取 modelCode 用于数据选择器引用)
- `apaas-create-model` (创建新模型)
- `apaas-create-dict`
- `apaas-create-form`

### 场景 5: 给已有模型追加字段
使用 Skills:
- `apaas-query-model` (查询已有模型，获取 modelCode + modelId + 已有字段列表)
- `apaas-add-field` (逐个追加新字段)

## 关键概念

### 随机后缀策略
所有编码（appCode 除外）都建议添加随机后缀避免冲突：
```python
import random, string

suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
model_code = f"customer_{suffix}"  # customer_a1b2
```

### 编码映射
- `code_map`: 原始模型编码 → 带后缀的模型编码
- `dict_code_map`: 原始字典编码 → 带后缀的字典编码

在表单组件中必须使用映射后的编码。

### Reserved Words
避免使用数据库保留字作为字段编码，常见保留字：
- `name`, `status`, `type`, `order`, `group`, `key`, `value`, `index`
- `level`, `date`, `time`, `user`, `role`, `id`, `comment`, `location`
- `email`, `phone`, `address`, `account`, `model`, `manager`, `priority`

解决方法：添加前缀 `f_`，如 `f_status`, `f_name`

## 参考资料

- [完整 API 参考](../memory/apaas-builder-skill.md)
- [测试脚本](../scripts/test_full_deploy.py)
- [生成示例](../scripts/gen_afterservice.py)

## 贡献

欢迎补充更多组件 Skills 和使用示例。

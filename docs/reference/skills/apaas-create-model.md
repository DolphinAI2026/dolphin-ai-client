# aPaaS Create Data Model

## 用途
在应用下批量创建数据模型（支持主表和子表）

## API 端点
```
POST /xdap-app/common/resource/v2/appModel
```

## 请求头
```json
{
  "Content-Type": "application/json",
  "xdaptenantid": "<tenant_id>",
  "xdaptimestamp": "<millisecond_timestamp>",
  "xdaptoken": "<auth_token>",
  "appid": "<app_id>"
}
```

## 请求格式
```json
{
  "appId": "123456789",
  "datasourceId": "",
  "dataModels": [
    {
      "appId": "123456789",
      "modelName": "客户",
      "modelCode": "customer_a1b2",
      "modelDescription": "客户主数据",
      "fields": [
        {
          "fieldName": "客户名称",
          "fieldCode": "customer_name",
          "fieldType": "STRING",
          "fieldDescription": "单行输入"
        },
        {
          "fieldName": "联系电话",
          "fieldCode": "contact_phone",
          "fieldType": "STRING",
          "fieldDescription": "手机号码"
        }
      ]
    }
  ]
}
```

## 参数说明

### 顶层参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appId | string | 是 | 应用 ID |
| datasourceId | string | 否 | 数据源 ID，可为空字符串 |
| dataModels | array | 是 | 数据模型数组 |

### dataModels 数组元素
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appId | string | 是 | 应用 ID |
| modelName | string | 是 | 模型名称（中文） |
| modelCode | string | 是 | 模型编码，必须符合 `^[a-zA-Z][a-zA-Z0-9_]{1,64}$` |
| modelDescription | string | 否 | 模型描述 |
| fields | array | 是 | 字段数组 |

### fields 数组元素
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| fieldName | string | 是 | 字段名称（中文） |
| fieldCode | string | 是 | 字段编码，只能包含字母、数字、下划线 |
| fieldType | string | 是 | 字段类型：STRING, NUM, DATE, BIG_TEXT |
| fieldDescription | string | 否 | 字段描述 |

## 字段类型映射

| 预览类型 | 数据模型字段类型 | 说明 |
|---------|---------------|------|
| 单据号 | STRING | 自动编号字段 |
| 单行输入 | STRING | 普通文本 |
| 多行输入 | BIG_TEXT | 长文本 |
| 手机号码 | STRING | 手机号 |
| 电子邮箱 | STRING | 邮箱 |
| 下拉单选 | STRING | 字典单选 |
| 下拉多选 | STRING | 字典多选 |
| 数据单选 | STRING | 关联其他模型 |
| 日期时间 | DATE | 日期 |
| 金额 | NUM | 货币 |
| 数字 | NUM | 数值 |
| 附件上传 | STRING | 文件 |
| 开关 | STRING | 布尔值 |
| 人员选择 | STRING | 用户选择器 |
| 地理位置 | STRING | 位置 |
| 子表 | — | 不生成字段，单独创建子表模型 |

## 响应格式
```json
{
  "code": "ok",
  "data": [
    {
      "id": "model_id_1",
      "modelCode": "customer_a1b2",
      "modelName": "客户",
      ...
    }
  ]
}
```

返回数组包含所有创建的模型对象。

## Python 调用示例

### 使用 config_transformer
```python
from app.config_transformer import transform_models
from app.apaas_client import APaaSClient

async def create_models_example(client: APaaSClient, app_id: str):
    # 预览格式的模型定义
    models = [
        {
            "name": "客户",
            "code": "customer",
            "fields": [
                {"name": "客户名称", "code": "customer_name", "type": "单行输入"},
                {"name": "联系电话", "code": "contact_phone", "type": "手机号码"},
                {"name": "客户等级", "code": "customer_level", "type": "下拉单选", "dict": "level"},
                {"name": "备注", "code": "remark", "type": "多行输入"}
            ]
        }
    ]

    # 转换为 API 格式（自动添加随机后缀避免冲突）
    payload, code_map = transform_models(app_id, models)

    # 调用 API
    result = await client.create_models(app_id, payload)

    print(f"创建了 {len(result)} 个模型")
    print(f"模型编码映射: {code_map}")
    return result, code_map
```

### 子表模型示例
```python
async def create_models_with_subtable(client: APaaSClient, app_id: str):
    models = [
        {
            "name": "工单",
            "code": "service_order",
            "fields": [
                {"name": "工单号", "code": "order_no", "type": "单据号"},
                {"name": "客户", "code": "customer_ref", "type": "数据单选", "ref": {"model": "customer", "field": "customer_name"}},
                # 子表字段
                {
                    "name": "费用明细",
                    "type": "子表",
                    "sub_code": "order_fee",
                    "sub_fields": [
                        {"name": "费用类型", "code": "fee_type", "type": "下拉单选", "dict": "fee_type"},
                        {"name": "金额", "code": "amount", "type": "金额"}
                    ]
                }
            ]
        }
    ]

    payload, code_map = transform_models(app_id, models)

    # payload.dataModels 会包含 2 个模型：
    # 1. service_order_xxxx (主表)
    # 2. order_fee_xxxx (子表)

    result = await client.create_models(app_id, payload)
    return result, code_map
```

## 注意事项

### modelCode 编码规则
- 必须以字母开头
- 只能包含字母、数字、下划线
- 长度 2-65 字符
- **建议添加随机后缀**避免重复（如 `customer_a1b2`）

### fieldCode 编码规则
- 只能包含字母、数字、下划线
- **避免使用数据库保留字**，否则会报错 "字段编码与数据库关键字重复"
- 常见保留字：`name`, `status`, `type`, `order`, `group`, `key`, `value`, `index`, `level`, `date`, `time`, `user`, `role`, `id`, `comment`, `location`, `email`, `phone`, `address`, `account`, `model`, `manager`, `priority`, `amount`, `currency`, `operator`
- 解决方法：添加前缀 `f_`，如 `f_status`, `f_name`

### 子表处理
- 子表需要单独创建一个数据模型
- 子表模型的 `modelCode` 通常为 `{主表code}_sub`
- 子表字段不包含在主表模型中
- 系统会自动创建 `tab_doc_id` 外键关联主表

### 随机后缀策略
```python
import random, string

def _rand(n=4):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

suffix = _rand(4)
model_code = f"customer_{suffix}"  # customer_a1b2
```

### Reserved Words 处理
```python
import re

RESERVED_WORDS = {
    'name', 'status', 'type', 'order', 'group', 'key', 'value', 'index',
    'table', 'column', 'select', 'insert', 'update', 'delete', 'create',
    'drop', 'alter', 'from', 'where', 'join', 'on', 'in', 'is', 'not',
    'null', 'and', 'or', 'like', 'between', 'having', 'limit', 'offset',
    'desc', 'asc', 'set', 'into', 'values', 'as', 'by', 'all', 'any',
    'exists', 'case', 'when', 'then', 'else', 'end', 'if', 'for', 'each',
    'action', 'result', 'level', 'role', 'user', 'date', 'time', 'timestamp',
    'comment', 'location', 'email', 'phone', 'address', 'account', 'model',
    'unit', 'category', 'manager', 'priority', 'amount', 'currency',
    'operator', 'spec', 'id',
}

def _safe_code(code: str) -> str:
    """Sanitize code: only alphanumeric/underscore, prefix reserved words."""
    c = re.sub(r'[^a-zA-Z0-9_]', '_', code)
    if c.lower() in RESERVED_WORDS:
        c = f"f_{c}"
    return c
```

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 12005 | 模型数据源为空 | 旧版 API 需要 datasourceId | 使用 `/common/resource/v2/appModel` 端点 |
| - | 字段编码与数据库关键字重复 | fieldCode 是保留字 | 添加前缀 `f_` 或重命名 |
| - | 模型编码已存在 | modelCode 重复 | 添加随机后缀 |
| - | 不符合编码规则 | code 包含非法字符（如 `/`） | 使用 `re.sub(r'[^a-zA-Z0-9_]', '_', code)` 清理 |

## 相关 Skills
- `apaas-create-app` — 创建应用（获取 appId）
- `apaas-create-form` — 创建表单配置（使用模型）
- `apaas-comp-son-table` — 子表组件配置

# aPaaS Create Data Dictionary

## 用途
在应用下批量创建数据字典（用于下拉选择组件）

## API 端点
```
POST /xdap-app/common/resource/appDict
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
[
  {
    "appId": "123456789",
    "dictionaryCode": "customer_level_a1b2",
    "dictionaryName": "客户等级",
    "dictionaryOptions": [
      {
        "optionName": "VIP",
        "optionCode": "vip_a1b2",
        "displayOrder": 1,
        "remarks": ""
      },
      {
        "optionName": "普通",
        "optionCode": "normal_a1b2",
        "displayOrder": 2,
        "remarks": ""
      }
    ]
  }
]
```

## 参数说明

### 字典对象
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appId | string | 是 | 应用 ID |
| dictionaryCode | string | 是 | 字典编码，全局唯一，建议添加随机后缀 |
| dictionaryName | string | 是 | 字典名称（中文） |
| dictionaryOptions | array | 是 | 字典选项数组 |

### dictionaryOptions 数组元素
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| optionName | string | 是 | 选项名称（显示值） |
| optionCode | string | 是 | 选项编码，**全局唯一**（跨所有字典） |
| displayOrder | number | 是 | 显示顺序，从 1 开始 |
| remarks | string | 否 | 备注 |

## 响应格式
```json
{
  "code": "ok",
  "data": {}
}
```

## Python 调用示例

### 使用 config_transformer
```python
from app.config_transformer import transform_dicts
from app.apaas_client import APaaSClient

async def create_dicts_example(client: APaaSClient, app_id: str):
    # 预览格式的字典定义
    dicts = [
        {
            "name": "客户等级",
            "code": "customer_level",
            "options": [
                {"name": "VIP", "code": "vip"},
                {"name": "普通", "code": "normal"},
                {"name": "战略客户", "code": "strategic"}
            ]
        },
        {
            "name": "区域",
            "code": "region",
            "options": [
                {"name": "中国区", "code": "cn"},
                {"name": "欧洲区", "code": "eu"},
                {"name": "北美区", "code": "na"}
            ]
        }
    ]

    # 转换为 API 格式（自动添加随机后缀避免冲突）
    payload, dict_code_map = transform_dicts(app_id, dicts)

    # 调用 API
    await client.create_dicts(app_id, payload)

    print(f"创建了 {len(payload)} 个字典")
    print(f"字典编码映射: {dict_code_map}")
    # dict_code_map: {"customer_level": "customer_level_a1b2", "region": "region_a1b2"}
    return dict_code_map
```

### 支持多种选项格式
```python
# 格式 1: 字符串数组（自动生成 code）
dicts = [
    {
        "name": "优先级",
        "code": "priority",
        "options": ["紧急", "高", "中", "低"]
    }
]

# 格式 2: 对象数组（指定 code）
dicts = [
    {
        "name": "优先级",
        "code": "priority",
        "options": [
            {"name": "紧急", "code": "urgent"},
            {"name": "高", "code": "high"},
            {"name": "中", "code": "medium"},
            {"name": "低", "code": "low"}
        ]
    }
]

# 格式 3: 混合格式（兼容 label/id 字段）
dicts = [
    {
        "name": "状态",
        "code": "status",
        "options": [
            {"label": "启用", "id": "enabled"},
            {"label": "停用", "id": "disabled"}
        ]
    }
]
```

### transform_dicts 实现
```python
from typing import List, Dict, Tuple
import random, string

def _rand(n: int = 4) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def transform_dicts(app_id: str, dicts: List[Dict]) -> Tuple[List[Dict], Dict[str, str]]:
    """构建 /common/resource/appDict 请求体，支持 str 和 dict 格式的选项。
    返回 (payload, dict_code_map)，dict_code_map 记录原始code→带后缀code的映射。
    """
    suffix = _rand(4)
    result = []
    dict_code_map: Dict[str, str] = {}  # original_code → suffixed_code

    for d in dicts:
        base_code = d.get("code", "dict")
        dict_code = f"{base_code}_{suffix}"
        dict_code_map[d.get("code", base_code)] = dict_code

        options = d.get("options", [])
        dict_options = []
        for i, opt in enumerate(options):
            if isinstance(opt, str):
                opt_name = opt
                opt_code = f"{base_code}_{i+1}_{suffix}"
            elif isinstance(opt, dict):
                opt_name = opt.get("name", opt.get("label", str(opt)))
                raw_opt_code = opt.get("code", opt.get("id", f"{base_code}_{i+1}"))
                opt_code = f"{raw_opt_code}_{suffix}"
            else:
                opt_name = str(opt)
                opt_code = f"{base_code}_{i+1}_{suffix}"

            dict_options.append({
                "optionName": opt_name,
                "optionCode": opt_code,
                "displayOrder": i + 1,
                "remarks": ""
            })

        result.append({
            "appId": app_id,
            "dictionaryCode": dict_code,
            "dictionaryName": d["name"],
            "dictionaryOptions": dict_options
        })

    return result, dict_code_map
```

## 注意事项

### dictionaryCode 全局唯一
- 字典编码在**租户级别全局唯一**
- 重复会报错 "数据字典编码重复"
- **必须添加随机后缀**避免冲突：
  ```python
  suffix = _rand(4)
  dict_code = f"customer_level_{suffix}"  # customer_level_a1b2
  ```

### optionCode 全局唯一（重要！）
- 选项编码在**所有字典中全局唯一**
- 不同字典的选项编码也不能重复
- 错误示例：
  ```json
  // 字典 1
  {"dictionaryCode": "status", "options": [{"optionCode": "enabled"}]}
  // 字典 2
  {"dictionaryCode": "device_status", "options": [{"optionCode": "enabled"}]}  // ❌ 重复！
  ```
- 正确做法：给每个选项编码添加字典前缀 + 后缀
  ```python
  opt_code = f"{dict_code}_{opt_raw_code}_{suffix}"
  # 结果: customer_level_vip_a1b2, device_status_enabled_a1b2
  ```

### 字典编码映射（dict_code_map）
- 表单组件绑定字典时，需要使用**带后缀的字典编码**
- `transform_dicts` 返回的 `dict_code_map` 记录了原始编码到带后缀编码的映射
- 在 `transform_form_config` 中使用：
  ```python
  # 字段定义中引用原始 code
  field = {"type": "下拉单选", "dict": "customer_level"}

  # 表单组件中使用映射后的 code
  actual_dict_code = dict_code_map.get("customer_level", "customer_level")
  component["dictionarySelectConfig"] = {
      "dictionaryCode": actual_dict_code  # customer_level_a1b2
  }
  ```

### 字典选项顺序
- `displayOrder` 决定下拉框中的显示顺序
- 从 1 开始递增
- 不要跳号或重复

### 空字典占位
- 如果字段引用了未定义的字典，可以创建空字典占位：
  ```python
  {
      "dictionaryCode": "undefined_dict_a1b2",
      "dictionaryName": "undefined_dict",
      "dictionaryOptions": []
  }
  ```

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 13008 | 数据字典值编码重复 | optionCode 在全局范围内重复 | 给每个选项添加字典前缀 + 后缀 |
| - | 数据字典编码重复 | dictionaryCode 重复 | 添加随机后缀 |
| - | JSON parse error (ChooseOption) | dictionaryOptions 格式错误 | 必须是数组 `[]`，不能是对象 `{}` |

## 相关 Skills
- `apaas-create-app` — 创建应用（获取 appId）
- `apaas-comp-select-single` — 下拉单选组件（使用字典）
- `apaas-comp-select-multi` — 下拉多选组件（使用字典）

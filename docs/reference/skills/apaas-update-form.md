# aPaaS Update Form Configuration

## 用途
编辑已有表单配置（修改组件标签、属性、新增/删除组件、调整列表页等）

## 流程
修改表单配置需要**两步操作**：先查询完整表单配置，修改后回写。

```
1. GET  /v2/form/query/formContext?formId={formId}     → 获取完整 simpleFormConfig
2. POST /formConfig/save/formConfigDetail               → 修改后回写
```

## API 端点

### 保存表单配置（全量更新）
```
POST /xdap-app/formConfig/save/formConfigDetail
```

### 更新列表页配置
```
POST /xdap-app/formConfig/update/listPageConfig
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

## 保存表单配置

### 请求格式
将查询返回的完整 `simpleFormConfig` 对象修改目标字段后，直接作为请求体 POST。

主要可修改内容：
- `detailPage.formComponents` — 表单组件列表（修改标签、属性、新增/删除组件）
- `detailPage.webFormSettings` — PC 端表单样式
- `detailPage.mobileFormSettings` — 移动端表单样式

### 响应格式
```json
{
  "code": "ok",
  "message": "保存成功"
}
```

## 可修改的组件属性

### 通用属性
| 属性 | 类型 | 说明 |
|------|------|------|
| label | string | 字段标签（显示名称） |
| placeholder | string | 占位文本 |
| width | integer | 宽度栅格（6=半行, 12=整行） |
| height | integer | 高度 |
| hidden | boolean | 是否隐藏 |
| readOnly | boolean | 是否只读 |
| required | boolean | 是否必填 |
| uniqueCheck | boolean | 是否唯一校验 |
| lengthLimit | integer | 文本长度限制 |
| autoChangeLine | boolean | 是否自动换行 |

### 不可修改的属性
| 属性 | 说明 |
|------|------|
| uuid | 组件唯一标识，不要修改 |
| componentType | 组件类型，不要修改 |
| modelField | 绑定的模型字段，不要修改 |
| modelCode | 所属模型编码，不要修改 |
| boId | 业务对象 ID，不要修改 |
| boCode | 业务对象编码，不要修改 |

## Python 调用示例

### 修改组件标签
```python
from app.apaas_client import APaaSClient

async def update_component_label(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    field_code: str,
    new_label: str
):
    """修改指定字段的标签名称"""
    # 1. 查询完整表单配置
    result = await client.request(
        "GET",
        f"/xdap-app/v2/form/query/formContext?formId={form_id}",
        app_id=app_id
    )
    sfc = result["data"]["simpleFormConfig"]

    # 2. 找到目标组件并修改
    for comp in sfc["detailPage"]["formComponents"]:
        if comp.get("modelField", "").endswith(f".{field_code}"):
            comp["label"] = new_label
            print(f"修改 {comp['modelField']} 标签为: {new_label}")
            break

    # 3. 回写
    await client.request(
        "POST",
        "/xdap-app/formConfig/save/formConfigDetail",
        json=sfc,
        app_id=app_id
    )
    print("表单配置已更新")
```

### 修改组件属性（必填、只读等）
```python
async def update_component_props(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    field_code: str,
    **props
):
    """修改指定字段的属性

    props 可包含: required, readOnly, hidden, placeholder, width, lengthLimit 等
    """
    # 1. 查询
    result = await client.request(
        "GET",
        f"/xdap-app/v2/form/query/formContext?formId={form_id}",
        app_id=app_id
    )
    sfc = result["data"]["simpleFormConfig"]

    # 2. 修改
    for comp in sfc["detailPage"]["formComponents"]:
        if comp.get("modelField", "").endswith(f".{field_code}"):
            for key, value in props.items():
                comp[key] = value
            print(f"修改 {comp['modelField']}: {props}")
            break

    # 3. 回写
    await client.request(
        "POST",
        "/xdap-app/formConfig/save/formConfigDetail",
        json=sfc,
        app_id=app_id
    )
```

### 批量设置必填字段
```python
async def set_required_fields(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    required_field_codes: list
):
    """批量设置必填字段"""
    result = await client.request(
        "GET",
        f"/xdap-app/v2/form/query/formContext?formId={form_id}",
        app_id=app_id
    )
    sfc = result["data"]["simpleFormConfig"]

    for comp in sfc["detailPage"]["formComponents"]:
        model_field = comp.get("modelField", "")
        field_code = model_field.split(".")[-1] if "." in model_field else ""
        if field_code in required_field_codes:
            comp["required"] = True
            print(f"设置必填: {comp['label']} ({model_field})")

    await client.request(
        "POST",
        "/xdap-app/formConfig/save/formConfigDetail",
        json=sfc,
        app_id=app_id
    )
```

### 完整流程：查询表单 → 修改 → 保存
```python
async def update_form_example(client: APaaSClient, app_id: str):
    """完整的表单修改流程"""
    # 1. 查询菜单列表，获取 formId
    menus = await client.request(
        "POST",
        "/xdap-app/menu/query/manageAppMenu",
        json={"appId": app_id},
        app_id=app_id
    )
    form_menu = next(
        m for m in menus["data"]
        if m.get("menuType") == "MODEL" and "报名" in m.get("menuName", "")
    )
    form_id = form_menu["formId"]

    # 2. 查询表单详情
    result = await client.request(
        "GET",
        f"/xdap-app/v2/form/query/formContext?formId={form_id}",
        app_id=app_id
    )
    sfc = result["data"]["simpleFormConfig"]

    # 3. 修改组件
    for comp in sfc["detailPage"]["formComponents"]:
        if comp.get("label") == "客户名称":
            comp["required"] = True
            comp["placeholder"] = "请输入客户全称"

    # 4. 回写保存
    await client.request(
        "POST",
        "/xdap-app/formConfig/save/formConfigDetail",
        json=sfc,
        app_id=app_id
    )
    print("表单更新完成")
```

## 注意事项

### 必须传完整对象
- `formConfigDetail` 接口要求传入**完整的 simpleFormConfig 对象**
- 不能只传部分字段，否则其他配置会丢失
- 正确做法：先查询 → 修改目标字段 → 整体回写

### 不要修改结构性字段
- `uuid`、`componentType`、`modelField`、`modelCode`、`boId`、`boCode` 等不要修改
- 修改这些字段可能导致表单异常

### 新增组件的注意事项
- 新增组件需要生成唯一的 `uuid`（24 位十六进制字符串）
- 需要正确设置 `modelField`（模型编码.字段编码）
- 对应的模型字段必须已经存在
- 建议参考已有组件的完整结构

### 下拉选择组件绑定数据字典
当需要将下拉选择组件绑定到数据字典时，必须设置以下关键字段：

```python
# 查询字典信息
dict_id = "字典ID"
dict_code = "字典编码"

# 查询字典选项
options = [
    {"valueCode": "option1", "valueName": "选项1"},
    {"valueCode": "option2", "valueName": "选项2"}
]

# 构建 chooseOptions
choose_options = []
for i, opt in enumerate(options):
    choose_options.append({
        "id": opt["valueCode"],
        "label": opt["valueName"],
        "labelI18nAssociated": False,
        "color": "#027AFF",
        "status": "ENABLE",
        "displayOrder": i
    })

# 更新组件配置
component['source'] = {
    "type": "DICTIONARY_TYPE",
    "id": dict_id
}
component['chooseOptions'] = choose_options
component['dictionaryChooseOptions'] = choose_options
component['chooseType'] = 'SINGLE'  # 或 'MULTIPLE'
component['multicolor'] = False
```

**关键点：**
- `source.type` 必须是 `"DICTIONARY_TYPE"`
- `source.id` 是字典的 ID（不是 dictionaryCode）
- `chooseOptions` 和 `dictionaryChooseOptions` 必须都设置
- 选项的 `id` 使用 `valueCode`（不是字典选项的 ID）
- 不能只设置 `dictionarySelectConfig`，必须设置 `source` 和 `chooseOptions`

### objectVersionNumber
- simpleFormConfig 中包含 `objectVersionNumber`
- 每次保存后会自动递增
- 如果版本号不一致可能保存失败，需重新查询

### formId 的获取
- 通过 `POST /menu/query/manageAppMenu` 获取菜单列表
- 只有 `menuType: "MODEL"` 的菜单才有 `formId`

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| - | 保存失败 | simpleFormConfig 不完整 | 先查询完整对象再修改 |
| - | 版本冲突 | objectVersionNumber 不一致 | 重新查询后再修改 |
| 500 | Internal Server Error | formId 无效或时间戳格式错误 | 检查 formId 和时间戳 |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills
- `apaas-query-form` — 查询表单菜单和详情（获取 formId 和 simpleFormConfig）
- `apaas-create-form` — 创建表单配置
- `apaas-comp-*` — 各种表单组件的详细配置

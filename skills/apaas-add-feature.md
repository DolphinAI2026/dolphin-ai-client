# aPaaS 基于已有应用添加新功能

## 用途
在已有的 aPaaS 应用中添加新的业务功能，包括新增数据字典、角色、数据模型、表单等。

## 前置条件
- 已有应用的 `app_id`
- 已有应用的 `suffix`（用于保持命名一致性）
- 已有的 `dict_codes`、`role_codes`、`model_codes` 映射（可选，用于关联引用）

## 添加步骤

### Step 1: 加载已有应用信息
```python
import json

# 从进度文件加载
with open('/tmp/app_progress.json', 'r') as f:
    progress = json.load(f)

app_id = progress['app_id']
suffix = progress['suffix']
dict_codes = progress.get('dict_codes', {})
role_codes = progress.get('role_codes', {})
model_codes = progress.get('model_codes', {})
```

### Step 2: 添加新的数据字典
```python
from app.apaas_client import APaaSClient
import httpx

async def add_new_dicts(client: APaaSClient, progress: dict, new_dicts: list):
    """添加新的数据字典

    new_dicts 格式:
    [
        {
            "name": "订单状态",
            "code": "order_status",
            "options": [
                {"name": "待处理", "code": "pending"},
                {"name": "已完成", "code": "completed"}
            ]
        }
    ]
    """
    app_id = progress['app_id']
    suffix = progress['suffix']

    # 创建字典
    dict_payload = []
    for d in new_dicts:
        dict_code = f"{d['code']}_{suffix}"
        dict_payload.append({
            "appId": app_id,
            "dictionaryCode": dict_code,
            "dictionaryName": d['name'],
            "dictionaryOptions": []
        })
        progress['dict_codes'][d['name']] = dict_code

    await client.create_dicts(app_id, dict_payload)

    # 添加选项
    headers = client._get_headers(app_id)
    async with httpx.AsyncClient(verify=False, timeout=30.0) as http_client:
        # 查询字典 ID
        response = await http_client.post(
            f"{client.base_url}/xdap-app/dataDictionary/query/dataDictionaryList",
            headers=headers,
            json={"keyword": "", "appId": app_id}
        )
        result = response.json()
        dicts = result.get('table', [])

        # 为每个新字典添加选项
        for d_config in new_dicts:
            dict_code = f"{d_config['code']}_{suffix}"
            dict_obj = next((d for d in dicts if d.get('dictionaryCode') == dict_code), None)
            if not dict_obj:
                continue

            dict_id = dict_obj.get('id')

            for idx, opt in enumerate(d_config['options']):
                payload = {
                    "appId": app_id,
                    "dictionaryId": dict_id,
                    "valueCode": f"{opt['code']}_{suffix}",
                    "valueName": opt['name'],
                    "valueNameI18nAssociated": False,
                    "valueNameI18nResourceCode": "",
                    "valueNameI18n": {},
                    "displayOrder": idx,
                    "valueDescribe": "",
                    "valueStatus": "ENABLE",
                    "valueMulticolor": "#027AFF"
                }

                await http_client.post(
                    f"{client.base_url}/xdap-app/dataDictionary/add/dictionaryValue",
                    headers=headers,
                    json=payload
                )

    return progress
```

### Step 3: 添加新角色
```python
async def add_new_roles(client: APaaSClient, progress: dict, new_roles: list):
    """添加新角色

    new_roles 格式:
    [
        {"name": "审核员", "code": "auditor"},
        {"name": "财务", "code": "finance"}
    ]
    """
    app_id = progress['app_id']
    suffix = progress['suffix']

    roles_payload = []
    for r in new_roles:
        role_code = f"R_{r['code']}_{suffix}"
        roles_payload.append({
            "appId": app_id,
            "roleCode": role_code,
            "roleName": r['name']
        })
        progress['role_codes'][r['name']] = role_code

    try:
        await client.create_roles(app_id, roles_payload)
    except Exception as e:
        if "已存在" in str(e) or "重复" in str(e):
            print(f"角色已存在，跳过: {e}")
        else:
            raise

    return progress
```

### Step 4: 添加新数据模型
```python
async def add_new_models(client: APaaSClient, progress: dict, new_models: list):
    """添加新数据模型

    new_models 格式:
    [
        {
            "name": "订单",
            "code": "order",
            "fields": [
                {"name": "订单号", "code": "order_no", "type": "STRING"},
                {"name": "客户", "code": "customer_ref", "type": "STRING"},
                {"name": "订单金额", "code": "amount", "type": "NUM"}
            ]
        }
    ]
    """
    app_id = progress['app_id']
    suffix = progress['suffix']

    models = []
    for m in new_models:
        model_code = f"{m['code']}_{suffix}"

        fields = []
        for f in m['fields']:
            fields.append({
                "fieldName": f['name'],
                "fieldCode": f['code'],
                "fieldType": f['type'],
                "fieldDescription": ""
            })

        models.append({
            "appId": app_id,
            "modelName": m['name'],
            "modelCode": model_code,
            "modelDescription": m['name'],
            "fields": fields
        })

        progress['model_codes'][m['name']] = model_code

    payload = {
        "appId": app_id,
        "datasourceId": "",
        "dataModels": models
    }

    await client.create_models(app_id, payload)

    return progress
```

### Step 5: 添加新表单
```python
async def add_new_forms(client: APaaSClient, progress: dict, new_forms: list):
    """添加新表单

    new_forms 格式:
    [
        {
            "name": "订单",
            "model": "订单",  # 对应 model_codes 的 key
            "components": [
                {
                    "type": "FORM_DOCUMENT_NUMBER",
                    "label": "订单号",
                    "field": "order_no"
                },
                {
                    "type": "FORM_DATA_SELECTOR_SINGLE",
                    "label": "客户",
                    "field": "customer_ref",
                    "ref_model": "客户",  # 引用已有模型
                    "ref_field": "customer_name"
                },
                {
                    "type": "FORM_SELECT_INPUT_SINGLE",
                    "label": "订单状态",
                    "field": "order_status",
                    "dict": "订单状态"  # 引用字典
                }
            ]
        }
    ]
    """
    app_id = progress['app_id']
    suffix = progress['suffix']
    model_codes = progress['model_codes']
    dict_codes = progress['dict_codes']

    forms_payload = []

    for form_config in new_forms:
        model_code = model_codes[form_config['model']]
        form_code = f"form_{form_config['model'].lower()}_{suffix}"

        components = []
        query_conditions = []
        query_list = []
        listable_count = 0

        for comp_config in form_config['components']:
            comp_type = comp_config['type']
            field_code = comp_config['field']
            model_field = f"{model_code}.{field_code}"

            component = {
                "componentType": comp_type,
                "label": comp_config['label'],
                "modelField": model_field
            }

            # 处理数据选择器
            if comp_type == "FORM_DATA_SELECTOR_SINGLE":
                ref_model = model_codes[comp_config['ref_model']]
                component['dataSelectorConfig'] = {
                    "type": "LOV_CHOOSE",
                    "otherModelCode": ref_model,
                    "otherFieldCode": comp_config['ref_field']
                }

            # 处理字典下拉
            elif comp_type == "FORM_SELECT_INPUT_SINGLE":
                if 'dict' in comp_config:
                    dict_code = dict_codes[comp_config['dict']]
                    # 注意：这里需要查询字典选项，参考 phase5_create_forms
                    component['dictionarySelectConfig'] = {
                        "dictionaryCode": dict_code,
                        "dictionarySelectOptions": []  # 需要查询填充
                    }

            components.append(component)

            # 列表页配置
            if comp_type not in ['FORM_FILE_UPLOAD', 'FORM_TEXTAREA_INPUT', 'FORM_WIDGET_SON_TABLE']:
                if listable_count < 4:
                    query_conditions.append(model_field)
                if listable_count < 6:
                    query_list.append(model_field)
                listable_count += 1

        forms_payload.append({
            "formName": form_config['name'],
            "formCode": form_code,
            "allModelCodes": [model_code],
            "formComponents": components,
            "listPageView": {
                "queryConditions": query_conditions,
                "queryList": query_list
            }
        })

    await client.create_form_config(app_id, forms_payload)

    return progress
```

### Step 6: 修改已有表单（添加字段）
```python
async def add_field_to_existing_form(
    client: APaaSClient,
    app_id: str,
    form_name: str,
    new_field_config: dict
):
    """在已有表单中添加新字段

    new_field_config 格式:
    {
        "type": "FORM_TEXT_INPUT",
        "label": "新字段",
        "field": "new_field",
        "model_code": "Customer_inoe"
    }
    """
    import httpx
    import uuid

    headers = client._get_headers(app_id)

    async with httpx.AsyncClient(verify=False, timeout=30.0) as http_client:
        # 查询表单
        response = await http_client.post(
            f"{client.base_url}/xdap-app/menu/query/manageAppMenu",
            headers=headers,
            json={"appId": app_id}
        )
        result = response.json()

        menus = result.get('data', [])
        target_form = next((m for m in menus if m.get('menuName') == form_name), None)

        if not target_form:
            raise Exception(f"未找到表单: {form_name}")

        form_id = target_form.get('formId')

        # 查询表单配置
        response = await http_client.get(
            f"{client.base_url}/xdap-app/v2/form/query/formContext?formId={form_id}",
            headers=headers
        )
        result = response.json()

        form_config = result.get('data', {}).get('simpleFormConfig', {})
        components = form_config.get('detailPage', {}).get('formComponents', [])

        # 获取参考组件的 boId 和 boCode
        reference_comp = components[0] if components else None
        if not reference_comp:
            raise Exception("表单没有组件")

        bo_id = reference_comp.get('boId')
        model_code = new_field_config['model_code']

        # 创建新组件
        new_component = {
            "uuid": str(uuid.uuid4()).replace('-', '')[:24],
            "componentType": new_field_config['type'],
            "label": new_field_config['label'],
            "modelField": f"{model_code}.{new_field_config['field']}",
            "modelCode": model_code,
            "boId": bo_id,
            "boCode": f"{model_code}~{new_field_config['field']}",
            "width": 6,
            "required": False,
            "readOnly": False,
            "hidden": False,
            "placeholder": f"请输入{new_field_config['label']}"
        }

        # 添加到组件列表
        components.append(new_component)

        # 保存
        response = await http_client.post(
            f"{client.base_url}/xdap-app/formConfig/save/formConfigDetail",
            headers=headers,
            json=form_config
        )
        result = response.json()

        if result.get('code') != 'ok':
            raise Exception(f"保存失败: {result.get('message', '')}")

        print(f"✓ 已在表单 {form_name} 中添加字段: {new_field_config['label']}")
```

## 完整示例

### 示例 1: 添加新的业务模块
```python
async def add_order_module():
    """在客户管理系统中添加订单模块"""
    client = APaaSClient()
    await client.login("username", "password")

    # 加载已有应用信息
    with open('/tmp/crm_progress.json', 'r') as f:
        progress = json.load(f)

    # 1. 添加订单相关字典
    new_dicts = [
        {
            "name": "订单状态",
            "code": "order_status",
            "options": [
                {"name": "待处理", "code": "pending"},
                {"name": "处理中", "code": "processing"},
                {"name": "已完成", "code": "completed"},
                {"name": "已取消", "code": "cancelled"}
            ]
        },
        {
            "name": "支付方式",
            "code": "payment_method",
            "options": [
                {"name": "现金", "code": "cash"},
                {"name": "银行转账", "code": "bank_transfer"},
                {"name": "在线支付", "code": "online"}
            ]
        }
    ]
    progress = await add_new_dicts(client, progress, new_dicts)

    # 2. 添加订单相关角色
    new_roles = [
        {"name": "订单管理员", "code": "order_admin"},
        {"name": "财务", "code": "finance"}
    ]
    progress = await add_new_roles(client, progress, new_roles)

    # 3. 添加订单数据模型
    new_models = [
        {
            "name": "订单",
            "code": "order",
            "fields": [
                {"name": "订单号", "code": "order_no", "type": "STRING"},
                {"name": "客户", "code": "customer_ref", "type": "STRING"},
                {"name": "订单金额", "code": "amount", "type": "NUM"},
                {"name": "订单状态", "code": "order_status", "type": "STRING"},
                {"name": "支付方式", "code": "payment_method", "type": "STRING"},
                {"name": "下单时间", "code": "order_time", "type": "DATE"},
                {"name": "备注", "code": "remark", "type": "BIG_TEXT"}
            ]
        }
    ]
    progress = await add_new_models(client, progress, new_models)

    # 4. 添加订单表单
    new_forms = [
        {
            "name": "订单",
            "model": "订单",
            "components": [
                {"type": "FORM_DOCUMENT_NUMBER", "label": "订单号", "field": "order_no"},
                {
                    "type": "FORM_DATA_SELECTOR_SINGLE",
                    "label": "客户",
                    "field": "customer_ref",
                    "ref_model": "客户",
                    "ref_field": "customer_name"
                },
                {"type": "FORM_MONEY_INPUT", "label": "订单金额", "field": "amount"},
                {
                    "type": "FORM_SELECT_INPUT_SINGLE",
                    "label": "订单状态",
                    "field": "order_status",
                    "dict": "订单状态"
                },
                {
                    "type": "FORM_SELECT_INPUT_SINGLE",
                    "label": "支付方式",
                    "field": "payment_method",
                    "dict": "支付方式"
                },
                {"type": "FORM_DATEPICK_INPUT", "label": "下单时间", "field": "order_time"},
                {"type": "FORM_TEXTAREA_INPUT", "label": "备注", "field": "remark"}
            ]
        }
    ]
    progress = await add_new_forms(client, progress, new_forms)

    # 保存进度
    with open('/tmp/crm_progress.json', 'w') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

    print("✓ 订单模块添加完成")
```

### 示例 2: 为已有表单添加字段
```python
async def add_field_to_customer_form():
    """在客户表单中添加"客户来源"字段"""
    client = APaaSClient()
    await client.login("username", "password")

    with open('/tmp/crm_progress.json', 'r') as f:
        progress = json.load(f)

    app_id = progress['app_id']

    # 先添加"客户来源"字典
    new_dicts = [{
        "name": "客户来源",
        "code": "customer_source",
        "options": [
            {"name": "线上推广", "code": "online"},
            {"name": "线下活动", "code": "offline"},
            {"name": "客户推荐", "code": "referral"}
        ]
    }]
    progress = await add_new_dicts(client, progress, new_dicts)

    # 在客户表单中添加字段
    await add_field_to_existing_form(
        client,
        app_id,
        "客户主数据",
        {
            "type": "FORM_SELECT_INPUT_SINGLE",
            "label": "客户来源",
            "field": "customer_source",
            "model_code": progress['model_codes']['客户主数据']
        }
    )

    print("✓ 已在客户表单中添加客户来源字段")
```

## 注意事项

### 保持命名一致性
- 使用相同的 `suffix` 确保新资源与已有资源命名风格一致
- 字典编码：`{code}_{suffix}`
- 角色编码：`R_{code}_{suffix}`
- 模型编码：`{code}_{suffix}`

### 引用已有资源
- 数据选择器引用已有模型时，使用 `model_codes` 中的完整编码
- 字典下拉引用已有字典时，使用 `dict_codes` 中的完整编码
- 确保引用的资源已经存在

### 进度文件管理
- 每次添加新资源后更新进度文件
- 进度文件包含所有资源的映射关系
- 便于后续继续添加功能或修改

### 字段添加到模型
- 如果要在表单中添加新字段，必须先在数据模型中添加该字段
- 可以通过 API 或界面手动添加模型字段
- 表单字段的 `modelField` 必须对应已存在的模型字段

### 错误处理
- 角色重复创建不应阻断流程，使用 try-catch 跳过
- 字典、模型、表单重复会报错，需要检查是否已存在
- 保存表单配置前确保所有引用的资源都已创建

## 相关 Skills
- `apaas-create-complete-app` — 从零创建完整应用
- `apaas-create-dict` — 创建数据字典
- `apaas-create-role` — 创建角色
- `apaas-create-model` — 创建数据模型
- `apaas-create-form` — 创建表单
- `apaas-update-form` — 修改表单配置

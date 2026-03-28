# aPaaS 完整应用创建流程

## 用途
从零开始创建一个完整的 aPaaS 应用，包含数据字典、角色、数据模型、表单等所有资源。

## 创建步骤

### Phase 1: 创建应用
```python
from app.apaas_client import APaaSClient
import random, string

async def phase1_create_app(client: APaaSClient, app_name: str):
    """创建应用并生成唯一后缀"""
    # 生成随机后缀避免冲突
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    app_code = f"{app_name.lower().replace(' ', '-')}-{suffix}"

    result = await client.create_app(
        app_name=app_name,
        app_code=app_code,
        description=f"{app_name}应用"
    )

    app_id = str(result.get("id", result))

    # 保存进度
    progress = {
        "app_id": app_id,
        "app_code": app_code,
        "suffix": suffix,
        "dict_codes": {},
        "role_codes": {},
        "model_codes": {}
    }

    return progress
```

### Phase 2: 创建数据字典（含选项）
```python
async def phase2_create_dicts(client: APaaSClient, progress: dict, dicts_config: list):
    """创建数据字典并添加选项

    dicts_config 格式:
    [
        {
            "name": "客户等级",
            "code": "customer_level",
            "options": [
                {"name": "VIP", "code": "vip"},
                {"name": "普通", "code": "normal"}
            ]
        }
    ]
    """
    app_id = progress['app_id']
    suffix = progress['suffix']

    # Step 1: 创建字典（不含选项）
    dict_payload = []
    for d in dicts_config:
        dict_code = f"{d['code']}_{suffix}"
        dict_payload.append({
            "appId": app_id,
            "dictionaryCode": dict_code,
            "dictionaryName": d['name'],
            "dictionaryOptions": []
        })
        progress['dict_codes'][d['name']] = dict_code

    await client.create_dicts(app_id, dict_payload)

    # Step 2: 查询字典 ID
    import httpx
    headers = client._get_headers(app_id)

    async with httpx.AsyncClient(verify=False, timeout=30.0) as http_client:
        response = await http_client.post(
            f"{client.base_url}/xdap-app/dataDictionary/query/dataDictionaryList",
            headers=headers,
            json={"keyword": "", "appId": app_id}
        )
        result = response.json()
        dicts = result.get('table', [])

        # Step 3: 为每个字典添加选项
        for d_config in dicts_config:
            dict_code = f"{d_config['code']}_{suffix}"

            # 找到对应的字典
            dict_obj = next((d for d in dicts if d.get('dictionaryCode') == dict_code), None)
            if not dict_obj:
                continue

            dict_id = dict_obj.get('id')

            # 添加选项
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

### Phase 3: 创建角色
```python
async def phase3_create_roles(client: APaaSClient, progress: dict, roles_config: list):
    """创建角色

    roles_config 格式:
    [
        {"name": "管理员", "code": "admin"},
        {"name": "普通用户", "code": "user"}
    ]
    """
    app_id = progress['app_id']
    suffix = progress['suffix']

    roles_payload = []
    for r in roles_config:
        role_code = f"R_{r['code']}_{suffix}"
        roles_payload.append({
            "appId": app_id,
            "roleCode": role_code,
            "roleName": r['name']
        })
        progress['role_codes'][r['name']] = role_code

    await client.create_roles(app_id, roles_payload)

    return progress
```

### Phase 4: 创建数据模型
```python
async def phase4_create_models(client: APaaSClient, progress: dict, models_config: list):
    """创建数据模型

    models_config 格式:
    [
        {
            "name": "客户",
            "code": "customer",
            "fields": [
                {"name": "客户名称", "code": "customer_name", "type": "STRING"},
                {"name": "联系电话", "code": "contact_phone", "type": "STRING"},
                {"name": "备注", "code": "remark", "type": "BIG_TEXT"}
            ]
        }
    ]
    """
    app_id = progress['app_id']
    suffix = progress['suffix']

    models = []
    for m in models_config:
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

### Phase 5: 创建表单
```python
async def phase5_create_forms(client: APaaSClient, progress: dict, forms_config: list):
    """创建表单

    forms_config 格式:
    [
        {
            "name": "客户",
            "model": "客户",  # 对应 model_codes 的 key
            "components": [
                {
                    "type": "FORM_DOCUMENT_NUMBER",
                    "label": "客户ID",
                    "field": "customer_id"
                },
                {
                    "type": "FORM_TEXT_INPUT",
                    "label": "客户名称",
                    "field": "customer_name"
                },
                {
                    "type": "FORM_SELECT_INPUT_SINGLE",
                    "label": "客户等级",
                    "field": "customer_level",
                    "dict": "客户等级"  # 对应 dict_codes 的 key
                }
            ]
        }
    ]
    """
    app_id = progress['app_id']
    suffix = progress['suffix']
    model_codes = progress['model_codes']
    dict_codes = progress['dict_codes']

    forms = []
    for f_config in forms_config:
        model_code = model_codes[f_config['model']]
        form_code = f"form_{f_config['model'].lower()}_{suffix}"

        components = []
        list_fields = []
        query_fields = []

        for idx, comp in enumerate(f_config['components']):
            field_code = comp['field']
            model_field = f"{model_code}.{field_code}"

            component = {
                "componentType": comp['type'],
                "label": comp['label'],
                "modelField": model_field
            }

            # 如果是下拉选择且指定了字典
            if comp['type'] == 'FORM_SELECT_INPUT_SINGLE' and 'dict' in comp:
                dict_code = dict_codes[comp['dict']]

                # 需要查询字典选项
                import httpx
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
                    dict_obj = next((d for d in dicts if d.get('dictionaryCode') == dict_code), None)

                    if dict_obj:
                        dict_id = dict_obj.get('id')

                        # 查询选项
                        response = await http_client.post(
                            f"{client.base_url}/xdap-app/dataDictionary/query/dictionaryValueList",
                            headers=headers,
                            json={"dictionaryId": dict_id}
                        )
                        result = response.json()
                        options = result.get('table', [])

                        component['dictionarySelectConfig'] = {
                            "dictionaryCode": dict_code,
                            "dictionarySelectOptions": [
                                {"id": opt.get('valueCode'), "label": opt.get('valueName')}
                                for opt in options
                            ]
                        }

            components.append(component)

            # 列表页字段（排除附件、多行输入等）
            if comp['type'] not in ['FORM_FILE_UPLOAD', 'FORM_TEXTAREA_INPUT']:
                if len(query_fields) < 4:
                    query_fields.append(model_field)
                if len(list_fields) < 6:
                    list_fields.append(model_field)

        forms.append({
            "formName": f_config['name'],
            "formCode": form_code,
            "allModelCodes": [model_code],
            "formComponents": components,
            "listPageView": {
                "queryConditions": query_fields,
                "queryList": list_fields
            }
        })

    await client.create_form_config(app_id, forms)

    return progress
```

## 完整示例

```python
async def create_complete_app():
    """创建一个完整的客户管理应用"""
    client = APaaSClient()
    await client.login("username", "password")

    # Phase 1: 创建应用
    progress = await phase1_create_app(client, "客户管理系统")
    print(f"✓ Phase 1: 创建应用 (ID: {progress['app_id']})")

    # Phase 2: 创建数据字典
    dicts_config = [
        {
            "name": "客户等级",
            "code": "customer_level",
            "options": [
                {"name": "VIP", "code": "vip"},
                {"name": "普通", "code": "normal"}
            ]
        },
        {
            "name": "区域",
            "code": "region",
            "options": [
                {"name": "华东", "code": "east"},
                {"name": "华南", "code": "south"},
                {"name": "华北", "code": "north"}
            ]
        }
    ]
    progress = await phase2_create_dicts(client, progress, dicts_config)
    print(f"✓ Phase 2: 创建 {len(dicts_config)} 个数据字典")

    # Phase 3: 创建角色
    roles_config = [
        {"name": "管理员", "code": "admin"},
        {"name": "销售", "code": "sales"},
        {"name": "客服", "code": "service"}
    ]
    progress = await phase3_create_roles(client, progress, roles_config)
    print(f"✓ Phase 3: 创建 {len(roles_config)} 个角色")

    # Phase 4: 创建数据模型
    models_config = [
        {
            "name": "客户",
            "code": "customer",
            "fields": [
                {"name": "客户ID", "code": "customer_id", "type": "STRING"},
                {"name": "客户名称", "code": "customer_name", "type": "STRING"},
                {"name": "联系电话", "code": "contact_phone", "type": "STRING"},
                {"name": "客户等级", "code": "customer_level", "type": "STRING"},
                {"name": "所属区域", "code": "region", "type": "STRING"},
                {"name": "备注", "code": "remark", "type": "BIG_TEXT"}
            ]
        }
    ]
    progress = await phase4_create_models(client, progress, models_config)
    print(f"✓ Phase 4: 创建 {len(models_config)} 个数据模型")

    # Phase 5: 创建表单
    forms_config = [
        {
            "name": "客户",
            "model": "客户",
            "components": [
                {"type": "FORM_DOCUMENT_NUMBER", "label": "客户ID", "field": "customer_id"},
                {"type": "FORM_TEXT_INPUT", "label": "客户名称", "field": "customer_name"},
                {"type": "FORM_PHONE_INPUT", "label": "联系电话", "field": "contact_phone"},
                {"type": "FORM_SELECT_INPUT_SINGLE", "label": "客户等级", "field": "customer_level", "dict": "客户等级"},
                {"type": "FORM_SELECT_INPUT_SINGLE", "label": "所属区域", "field": "region", "dict": "区域"},
                {"type": "FORM_TEXTAREA_INPUT", "label": "备注", "field": "remark"}
            ]
        }
    ]
    progress = await phase5_create_forms(client, progress, forms_config)
    print(f"✓ Phase 5: 创建 {len(forms_config)} 个表单")

    print(f"\n✓ 应用创建完成！")
    print(f"  应用ID: {progress['app_id']}")
    print(f"  应用编码: {progress['app_code']}")

    return progress
```

## 注意事项

### 创建顺序不可变
1. 应用 → 2. 字典 → 3. 角色 → 4. 模型 → 5. 表单
- 字典和角色可以并行创建
- 模型必须在表单之前创建
- 表单组件引用的字典和模型必须已存在

### 后缀策略
- 所有资源编码都添加相同的随机后缀
- 避免重复创建时的编码冲突
- 后缀格式：4 位小写字母+数字

### 字典选项必须单独添加
- 创建字典时不能直接包含选项
- 必须先创建字典，查询字典 ID，再逐个添加选项
- 选项的 `valueCode` 也需要添加后缀

### 表单组件绑定字典
- 下拉选择组件需要查询字典的实际选项
- `dictionarySelectOptions` 中的 `id` 使用 `valueCode`
- 不是使用字典选项的数据库 ID

### 进度保存
- 每个 Phase 完成后保存进度到文件
- 包含 app_id、suffix、各资源的 code 映射
- 后续 Phase 可以从进度文件恢复

## 相关 Skills
- `apaas-create-app` — 创建应用
- `apaas-create-dict` — 创建数据字典
- `apaas-update-dict` — 添加字典选项
- `apaas-create-role` — 创建角色
- `apaas-create-model` — 创建数据模型
- `apaas-create-form` — 创建表单

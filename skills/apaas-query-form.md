# aPaaS Query Form Configuration

## 用途
查询应用下的表单菜单列表和表单配置详情（组件、列表页等）

## API 端点

### 查询菜单列表（含 formId）
```
POST /xdap-app/menu/query/manageAppMenu
```

### 查询表单配置详情
```
GET /xdap-app/v2/form/query/formContext
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

## 查询菜单列表

### 请求格式
```json
{
  "appId": "755484864311984128"
}
```

### 响应格式
```json
{
  "code": "ok",
  "message": "查询成功",
  "data": [
    {
      "id": "755574221093994496",
      "appId": "755484864311984128",
      "menuName": "报名信息表单",
      "menuType": "MODEL",
      "formId": "68c833d4e80b2743f2528ca0",
      "menuIcon": "userInfo",
      "menuOrder": 0,
      "cusIconStatus": "DISABLE",
      "menuDisplay": "ALL",
      "isEffective": true,
      "submenus": []
    },
    {
      "id": "755484864517505024",
      "menuName": "我的待办",
      "menuType": "TODO",
      "formId": ""
    }
  ]
}
```

### 菜单字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 菜单 ID |
| menuName | string | 菜单名称 |
| menuType | string | 菜单类型（见下方类型表） |
| formId | string | 表单 ID（`MODEL` 类型才有值） |
| menuOrder | integer | 菜单排序 |
| menuDisplay | string | 显示终端：ALL / PC / MOBILE |
| submenus | array | 子菜单列表（支持多级嵌套） |

### 菜单类型
| menuType | 说明 | 有 formId |
|----------|------|-----------|
| `MODEL` | 表单菜单 | ✅ |
| `TODO` | 我的待办 | ❌ |
| `TO_CHECK` | 我的待阅 | ❌ |
| `MY_SUBMIT` | 我发起的 | ❌ |
| `MY_PARTICIPATE` | 我的已办 | ❌ |
| `TODO_MANAGE` | 流程待办管理 | ❌ |
| `PROC_AUTH` | 流程授权 | ❌ |
| `PROC_FORWARD` | 流程转办 | ❌ |
| `TASK_CENTER` | 异步任务管理 | ❌ |
| `MENU_TYPE_DASHBOARD` | 仪表板 | ❌ |

## 查询表单配置详情

### 请求参数
| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| formId | query | string | 是 | 表单 ID（从菜单列表获取） |

### 请求示例
```
GET /xdap-app/v2/form/query/formContext?formId=68c833d4e80b2743f2528ca0
```

### 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "data": {
    "formId": "68c833d4e80b2743f2528ca0",
    "simpleFormConfig": {
      "id": "68c833d4e80b2743f2528ca0",
      "formCode": "form_abc123",
      "formName": "报名信息表单",
      "modelCode": "registration_info_fmrj",
      "status": "ENABLE",
      "allModelCodes": ["registration_info_fmrj"],
      "detailPage": {
        "formComponents": [
          {
            "uuid": "d9944c74a47ce1ac9407e91f",
            "componentType": "FORM_TEXT_INPUT",
            "label": "客户名称",
            "modelField": "registration_info_fmrj.customer_name_fmrj",
            "placeholder": "请输入",
            "width": 6,
            "height": 1,
            "hidden": false,
            "readOnly": false,
            "required": false,
            "uniqueCheck": false,
            "lengthLimit": 200,
            "modelCode": "registration_info_fmrj",
            "children": []
          }
        ],
        "webFormSettings": { "formLayout": 0 },
        "mobileFormSettings": { "formLayout": 0 }
      },
      "permissionGroups": [],
      "shareConfig": {},
      "objectVersionNumber": 1
    }
  }
}
```

### simpleFormConfig 主要字段
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 表单配置 ID（= formId） |
| formCode | string | 表单编码 |
| formName | string | 表单名称 |
| modelCode | string | 主模型编码 |
| status | string | 表单状态：ENABLE / DISABLE |
| allModelCodes | array | 关联的所有模型编码 |
| detailPage | object | 表单详情页配置 |
| detailPage.formComponents | array | 表单组件列表 |
| permissionGroups | array | 权限分组 |
| objectVersionNumber | integer | 乐观锁版本号 |

### formComponents 主要字段
| 字段 | 类型 | 说明 |
|------|------|------|
| uuid | string | 组件唯一 ID |
| componentType | string | 组件类型（FORM_TEXT_INPUT 等） |
| label | string | 字段标签 |
| modelField | string | 模型字段（modelCode.fieldCode） |
| modelCode | string | 所属模型编码 |
| placeholder | string | 占位文本 |
| width | integer | 宽度（栅格，6=半行，12=整行） |
| height | integer | 高度 |
| hidden | boolean | 是否隐藏 |
| readOnly | boolean | 是否只读 |
| required | boolean | 是否必填 |
| uniqueCheck | boolean | 是否唯一校验 |
| lengthLimit | integer | 长度限制 |

## Python 调用示例

### 查询应用下所有表单菜单
```python
from app.apaas_client import APaaSClient

async def query_form_menus(client: APaaSClient, app_id: str):
    """查询应用下所有表单菜单"""
    result = await client.request(
        "POST",
        "/xdap-app/menu/query/manageAppMenu",
        json={"appId": app_id},
        app_id=app_id
    )

    menus = result.get("data", [])
    form_menus = [m for m in menus if m.get("menuType") == "MODEL" and m.get("formId")]
    print(f"共 {len(form_menus)} 个表单菜单")
    for m in form_menus:
        print(f"  {m['menuName']} formId={m['formId']}")

    return form_menus
```

### 查询表单配置详情
```python
async def query_form_detail(client: APaaSClient, app_id: str, form_id: str):
    """查询表单配置详情"""
    result = await client.request(
        "GET",
        f"/xdap-app/v2/form/query/formContext?formId={form_id}",
        app_id=app_id
    )

    sfc = result.get("data", {}).get("simpleFormConfig", {})
    print(f"表单: {sfc.get('formName')} ({sfc.get('formCode')})")
    print(f"主模型: {sfc.get('modelCode')}")

    comps = sfc.get("detailPage", {}).get("formComponents", [])
    print(f"组件 ({len(comps)}):")
    for c in comps:
        print(f"  [{c['componentType']}] {c.get('label','')} → {c.get('modelField','')}")

    return sfc
```

### 按表单名称查找
```python
async def find_form_by_name(client: APaaSClient, app_id: str, form_name: str):
    """按菜单名称查找表单"""
    menus = await query_form_menus(client, app_id)
    for m in menus:
        if form_name in m["menuName"]:
            return await query_form_detail(client, app_id, m["formId"])
    return None
```

## 注意事项

### 两步查询
1. 先通过 `manageAppMenu` 获取菜单列表和 `formId`
2. 再通过 `formContext` 用 `formId` 查询表单详情
- 没有直接按 formCode 查询的接口

### formId 格式
- formId 是 MongoDB ObjectId 格式（24 位十六进制），如 `68c833d4e80b2743f2528ca0`
- 不是雪花 ID 格式

### 菜单树结构
- 菜单支持多级嵌套（`submenus` 字段）
- 表单菜单通常在第一级或第二级

### simpleFormConfig 用于更新
- 查询返回的 `simpleFormConfig` 可直接修改后用于 `formConfig/save/formConfigDetail` 更新
- 类似应用更新的"先查询完整对象 → 修改 → 回写"模式

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | formId 不存在 | 先查询菜单获取有效 formId |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills
- `apaas-create-form` — 创建表单配置
- `apaas-update-form` — 编辑表单配置
- `apaas-query-model` — 查询模型（获取 modelCode 用于理解表单字段）

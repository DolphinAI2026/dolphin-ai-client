## 查询表单配置详情

### 请求参数
| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| formId | query | string | 是 | 表单 ID |

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
| tableModelCode | string | 子表模型编码，当组件类型是FORM_WIDGET_SON_TABLE时必填 |

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

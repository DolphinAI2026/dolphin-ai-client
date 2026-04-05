## 自开发文件的上传

现在开始接入自开发文件上传，当用户在我的自开发文件中点击上传组件包的时候，去走下面的逻辑

1. workspaces 中对应执行 npm run build
2. 生成zip包之后，调用接口上传到平台
3. 具体上传到哪个平台需要看环境管理中配置的平台环境，如果只有一个环境那就上传到该环境，如果有多个环境，那就让用户选择一个环境进行上传


## 上传接口

url: `/xdap-app/selfdevelopment/add/developmentKit`
method: `POST`
headers:
    - xdaptenantid: 租户id
    - xdaptoken: token
body: `multipart/form-data`

```
{
    "file": "zip包",
    "fileType": "FRONTCOMPONENT",
    "description": "xxx",
    "uploadId": "1775374346635",
    "versionCode": "32位uuid",
    "useScope": "全部应用",
    "internalResource": false,
    "effectiveScope": "ALL_APPLICATION"
}
```

参数解释：
- file: zip包
- fileType: 根据类型选择下面的值
    - FRONTENGINE: 自开发页面
    - FRONTCOMPONENT: 自开发组件
    - FRONTLAYOUT: 自定义布局
    - FRONTLISTVIEW: 自定义列表视图
    - MFRONTENGINE: 移动端自开发页面
    - MFRONTCOMPONENT: 移动端自开发组件
    - FRONTTENANTCOMPONENT: 平台自开发插件
    - BACKENDENGINEPKG: 后端自开发包
- description: 生成一个组件的描述
- uploadId: 毫秒级时间戳
- versionCode: 32位uuid
- useScope: 使用范围 固定值 全部应用
- internalResource: 是否为内部资源 固定 false
- effectiveScope: 有效范围 固定值 ALL_APPLICATION

返回值:

```json
// 成功：
{
    "code": "ok",
    "message": "新增成功",
    "data": {
        "owner": "100169876816012509184",
        "createdBy": "100169876816012509184",
        "lastUpdatedBy": "100169876816012509184",
        "creationDate": "2026-04-05 15:32:49",
        "lastUpdateDate": "2026-04-05 15:32:49",
        "objectVersionNumber": 1,
        "tenantId": "825364441343197185",
        "id": "828653413179850752",
        "fileName": "form-component-chart-analysis.zip",
        "fileType": "FRONTCOMPONENT",
        "description": "",
        "ossObjectName": "96a549e7-6c14-4359-80d2-ae8844207504",
        "yeahMonthDate": "202604",
        "effectiveScope": "ALL_APPLICATION",
        "internalResource": false,
        "useScope": "全部应用",
        "fileTypeMeaning": "Web端自开发组件",
        "versionCode": "d50d02c3a45856f9516375cd294201cd"
    }
}

// 失败
{
    "code": "error",
    "message": "新增失败",
    "data": null
}
```

## 注意点

1. 上传时按钮需要loading
2. 上传失败或成功需要提示成功或失败信息
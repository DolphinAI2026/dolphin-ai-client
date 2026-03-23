# 增量更新 API 调用链路文档

> 本文档描述了增量更新功能的完整调用链路，包括前端、后端和得帆云平台 API 的交互流程。

## 目录

- [概述](#概述)
- [调用链路图](#调用链路图)
- [详细流程说明](#详细流程说明)
- [SSE 事件流](#sse-事件流)
- [API 端点详情](#api-端点详情)
- [关键文件索引](#关键文件索引)
- [错误处理](#错误处理)

---

## 概述

增量更新功能用于在应用配置变更后，只更新发生变化的资源（角色、字典、模型、表单、流程），而非全量重建。

### 核心流程

1. **差异计算**: 对比旧配置与新配置，识别变更项
2. **远程数据获取**: 从得帆云平台获取当前资源状态，用于匹配 remote_id
3. **流式执行**: 按顺序执行变更，通过 SSE 实时推送进度
4. **配置更新**: 执行成功后更新本地存储的配置

### 执行顺序

```
角色 (roles) → 字典 (dicts) → 模型 (models) → 表单 (forms) → 流程 (processes)
```

---

## 调用链路图

### 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           前端 (ChatPage.vue)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  executeIncrementalUpdate()                                                  │
│       │                                                                      │
│       ▼                                                                      │
│  incrementalApi.executeUpdateStream(appId, newConfig, token, callbacks)     │
│       │                                                                      │
│       ▼                                                                      │
│  new EventSource(url)  ──── SSE 连接 ────────────────────────┐              │
└─────────────────────────────────────────────────────────────────────────────┘
                                                                │
                                                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    后端 API (incremental_update.py)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  GET /applications/{app_id}/incremental/execute-stream                       │
│       │                                                                      │
│       ├── 1. JWT 解码验证 (query param: token)                               │
│       ├── 2. 获取用户和应用                                                   │
│       ├── 3. 解析 new_config (query param)                                   │
│       │                                                                      │
│       ▼                                                                      │
│  EventSourceResponse(event_generator())                                      │
│       │                                                                      │
│       ├── yield {"stage": "init", "step": "初始化..."}                       │
│       │                                                                      │
│       ├── fetch_remote_data(client, apaas_app_id) ─────────────┐            │
│       │        │                                                │            │
│       │        ▼                                                ▼            │
│       │   APaaSClient 调用:                              得帆云平台          │
│       │   - get_roles()                                                      │
│       │   - get_dicts() + get_dict_options()                                │
│       │   - get_models()                                                     │
│       │   - get_forms()                                                      │
│       │   - get_processes()                                                  │
│       │                                                                      │
│       ├── yield {"stage": "init", "step": "计算配置差异..."}                 │
│       │                                                                      │
│       ├── compute_config_diff(old_config, new_config, remote_data)          │
│       │                                                                      │
│       ▼                                                                      │
│  executor.execute_diff_stream(diff)                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                                                │
                                                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   IncrementalExecutor.execute_diff_stream()                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─── Stage 1: 角色 (roles) ───────────────────────────────────────────┐    │
│  │ for role in diff.role_changes:                                       │    │
│  │   yield {"stage": "roles", "current": i, "total": n}                │    │
│  │   │                                                                  │    │
│  │   ├─ added:    client.create_role(app_id, role_data)                │    │
│  │   ├─ modified: client.update_role(app_id, remote_id, role_data)     │    │
│  │   └─ deleted:  client.delete_role(app_id, remote_id)                │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─── Stage 2: 字典 (dicts) ───────────────────────────────────────────┐    │
│  │ for dict in diff.dict_changes:                                       │    │
│  │   yield {"stage": "dicts", "current": i, "total": n}                │    │
│  │   │                                                                  │    │
│  │   ├─ added:    client.create_dict(app_id, dict_data)                │    │
│  │   │            + for option in options:                              │    │
│  │   │                client.create_dict_option(app_id, dict_id, opt)  │    │
│  │   │                                                                  │    │
│  │   ├─ modified: client.update_dict(app_id, remote_id, dict_data)     │    │
│  │   │            + for option_change in option_changes:                │    │
│  │   │              ├─ added:    create_dict_option()                   │    │
│  │   │              ├─ modified: update_dict_option()                   │    │
│  │   │              └─ deleted:  delete_dict_option()                   │    │
│  │   │                                                                  │    │
│  │   └─ deleted:  (暂未实现平台删除)                                    │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─── Stage 3: 模型 (models) ──────────────────────────────────────────┐    │
│  │ for model in diff.model_changes:                                     │    │
│  │   yield {"stage": "models", "current": i, "total": n}               │    │
│  │   │                                                                  │    │
│  │   ├─ added:    client.create_model(app_id, model_data)              │    │
│  │   │            + for field in fields:                                │    │
│  │   │                client.create_field(app_id, model_id, field)     │    │
│  │   │                                                                  │    │
│  │   ├─ modified: for field_change in field_changes:                   │    │
│  │   │              ├─ added:    create_field()                         │    │
│  │   │              ├─ modified: update_field()                         │    │
│  │   │              └─ deleted:  delete_field()                         │    │
│  │   │                                                                  │    │
│  │   └─ deleted:  (暂未实现平台删除)                                    │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─── Stage 4: 表单 (forms) ───────────────────────────────────────────┐    │
│  │ for form in diff.form_changes:                                       │    │
│  │   yield {"stage": "forms", "current": i, "total": n}                │    │
│  │   │                                                                  │    │
│  │   ├─ added:    client.create_form(app_id, form_data)                │    │
│  │   ├─ modified: client.update_form(app_id, remote_id, form_data)     │    │
│  │   └─ deleted:  (暂未实现)                                            │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─── Stage 5: 流程 (processes) ───────────────────────────────────────┐    │
│  │ for process in diff.process_changes:                                 │    │
│  │   yield {"stage": "processes", "current": i, "total": n}            │    │
│  │   │                                                                  │    │
│  │   ├─ added:    client.create_process(app_id, process_data)          │    │
│  │   ├─ modified: client.update_process(app_id, remote_id, data)       │    │
│  │   └─ deleted:  (暂未实现)                                            │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  yield {"type": "complete", "result": execution_result}                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 得帆云平台 API 调用

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         得帆云平台 API                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  角色 API:                                                                   │
│    POST   /api/lowcode/role/add           → 创建角色                         │
│    PUT    /api/lowcode/role/update/{id}   → 更新角色                         │
│    DELETE /api/lowcode/role/delete/{id}   → 删除角色                         │
│                                                                              │
│  字典 API:                                                                   │
│    POST   /api/lowcode/dict/add           → 创建字典                         │
│    PUT    /api/lowcode/dict/update/{id}   → 更新字典                         │
│    POST   /api/lowcode/dict/option/add    → 创建字典选项                     │
│    PUT    /api/lowcode/dict/option/update → 更新字典选项                     │
│    DELETE /api/lowcode/dict/option/delete → 删除字典选项                     │
│                                                                              │
│  模型 API:                                                                   │
│    POST   /api/lowcode/model/add          → 创建模型                         │
│    PUT    /api/lowcode/model/update/{id}  → 更新模型                         │
│    POST   /api/lowcode/field/add          → 创建字段                         │
│    PUT    /api/lowcode/field/update/{id}  → 更新字段                         │
│    DELETE /api/lowcode/field/delete/{id}  → 删除字段                         │
│                                                                              │
│  表单 API:                                                                   │
│    POST   /api/lowcode/form/add           → 创建表单                         │
│    PUT    /api/lowcode/form/update/{id}   → 更新表单                         │
│                                                                              │
│  流程 API:                                                                   │
│    POST   /api/lowcode/process/add        → 创建流程                         │
│    PUT    /api/lowcode/process/update/{id}→ 更新流程                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 详细流程说明

### 1. 前端发起请求

**文件**: `frontend/src/views/ChatPage.vue`

```typescript
const executeIncrementalUpdate = async (newConfig: any) => {
  const token = userStore.token

  // 使用流式 API
  const cancel = incrementalApi.executeUpdateStream(
    currentApp.value.id,
    newConfig,
    token,
    // 进度回调
    (event) => {
      updateStepStatus(event.stage, event.status, event.step)
    },
    // 完成回调
    (result) => {
      if (result.success) {
        showSuccess('增量更新完成')
      }
    },
    // 错误回调
    (message) => {
      showError(message)
    }
  )
}
```

### 2. 前端 SSE 连接

**文件**: `frontend/src/api/incremental.ts`

```typescript
executeUpdateStream(
  appId: number,
  newConfig: any,
  token: string,
  onProgress: (event: StreamProgressEvent) => void,
  onComplete: (result: ExecuteResponse) => void,
  onError: (message: string) => void
): () => void {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
  const configParam = encodeURIComponent(JSON.stringify(newConfig))
  const url = `${baseUrl}/api/applications/${appId}/incremental/execute-stream?token=${token}&new_config=${configParam}`

  const eventSource = new EventSource(url)

  eventSource.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data)
    onProgress(data)
  })

  eventSource.addEventListener('done', (e) => {
    const data = JSON.parse(e.data)
    eventSource.close()
    onComplete(data.result)
  })

  eventSource.addEventListener('error', (e) => {
    onError(e.data?.message || '连接错误')
    eventSource.close()
  })

  // 返回取消函数
  return () => eventSource.close()
}
```

### 3. 后端 SSE 端点

**文件**: `backend/app/routes/incremental_update.py`

```python
@router.get("/{app_id}/incremental/execute-stream")
async def execute_update_stream(
    app_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Optional[str] = Query(None),
    new_config: Optional[str] = Query(None),
):
    # 1. JWT 验证（SSE 不支持 header，使用 query param）
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    user_id = int(payload.get("sub", 0))
    tenant_id = int(payload.get("tid"))

    # 2. 获取用户和应用
    current_user = await db.get(User, user_id)
    app = await db.get(Application, app_id)

    # 3. 解析配置
    new_config_dict = json.loads(new_config)

    # 4. 返回 SSE 响应
    return EventSourceResponse(event_generator())
```

### 4. 事件生成器

```python
async def event_generator():
    # 初始化阶段
    yield {"event": "progress", "data": json.dumps({"stage": "init", "step": "初始化..."})}

    # 获取远程数据
    client = APaaSClient(base_url, tenant_id, token)
    remote_data = await fetch_remote_data(client, apaas_app_id)

    # 计算差异
    diff = compute_config_diff(old_config, new_config_dict, remote_data)

    if not diff.has_changes:
        yield {"event": "done", "data": json.dumps({"type": "complete", "message": "无变更"})}
        return

    # 执行增量更新
    executor = IncrementalExecutor(client, app_id, app_name)

    async for event in executor.execute_diff_stream(diff):
        if event.get("type") == "complete":
            # 更新本地配置
            app.config_preview = json.dumps(new_config_dict)
            await session.commit()
            yield {"event": "done", "data": json.dumps(event)}
        elif event.get("type") == "error":
            yield {"event": "error", "data": json.dumps(event)}
        else:
            yield {"event": "progress", "data": json.dumps(event)}
```

### 5. 增量执行器

**文件**: `backend/app/incremental_executor.py`

```python
async def execute_diff_stream(self, diff: ConfigDiff) -> AsyncGenerator[Dict[str, Any], None]:
    results = {"roles": [], "dicts": [], "models": [], "forms": [], "processes": []}
    errors = []

    # Stage 1: 角色
    if diff.role_changes:
        total = len(diff.role_changes)
        for i, change in enumerate(diff.role_changes, 1):
            yield {
                "stage": "roles",
                "status": "running",
                "step": f"{self._change_action(change)}: {change.name}",
                "current": i,
                "total": total
            }
            try:
                await self._execute_role_change(change)
                results["roles"].append(f"{change.name} ({change.change_type})")
            except Exception as e:
                errors.append(f"角色 {change.name}: {str(e)}")

    # Stage 2-5: 字典、模型、表单、流程（类似逻辑）
    # ...

    # 完成
    yield {
        "type": "complete",
        "result": {
            "success": len(errors) == 0,
            "results": results,
            "errors": errors,
            "warnings": []
        }
    }
```

---

## SSE 事件流

### 事件类型

| 事件名 | 说明 | 数据结构 |
|--------|------|----------|
| `progress` | 进度更新 | `{stage, status, step, current?, total?}` |
| `done` | 执行完成 | `{type: "complete", result: ExecuteResponse}` |
| `error` | 执行错误 | `{type: "error", message: string}` |

### 完整事件流示例

```
event: progress
data: {"stage": "init", "status": "running", "step": "初始化..."}

event: progress
data: {"stage": "init", "status": "running", "step": "获取平台数据..."}

event: progress
data: {"stage": "init", "status": "running", "step": "计算配置差异..."}

event: progress
data: {"stage": "init", "status": "done", "step": "发现 2个角色变更, 3个字典变更, 1个模型变更"}

event: progress
data: {"stage": "roles", "status": "running", "step": "创建角色: 管理员", "current": 1, "total": 2}

event: progress
data: {"stage": "roles", "status": "running", "step": "更新角色: 普通用户", "current": 2, "total": 2}

event: progress
data: {"stage": "roles", "status": "done", "step": "角色更新完成"}

event: progress
data: {"stage": "dicts", "status": "running", "step": "创建字典: 订单状态", "current": 1, "total": 3}

event: progress
data: {"stage": "dicts", "status": "running", "step": "创建字典选项: 待支付", "current": 1, "total": 3, "detail": "订单状态"}

event: progress
data: {"stage": "dicts", "status": "running", "step": "更新字典: 支付方式", "current": 2, "total": 3}

event: progress
data: {"stage": "dicts", "status": "running", "step": "删除字典: 旧状态", "current": 3, "total": 3}

event: progress
data: {"stage": "dicts", "status": "done", "step": "字典更新完成"}

event: progress
data: {"stage": "models", "status": "running", "step": "创建模型字段: 客户姓名", "current": 1, "total": 1, "detail": "客户信息"}

event: progress
data: {"stage": "models", "status": "done", "step": "模型更新完成"}

event: progress
data: {"stage": "forms", "status": "running", "step": "无表单变更", "current": 0, "total": 0}

event: progress
data: {"stage": "processes", "status": "running", "step": "无流程变更", "current": 0, "total": 0}

event: done
data: {"type": "complete", "result": {"success": true, "results": {"roles": ["管理员 (added)", "普通用户 (modified)"], "dicts": ["订单状态 (added)", "支付方式 (modified)", "旧状态 (deleted)"], "models": ["客户信息 (modified)"], "forms": [], "processes": []}, "errors": [], "warnings": []}}
```

---

## API 端点详情

### 增量更新相关端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/applications/{app_id}/incremental/diff` | 计算配置差异 |
| `POST` | `/applications/{app_id}/incremental/preview` | 预览变更（同 diff） |
| `POST` | `/applications/{app_id}/incremental/execute` | 执行增量更新（非流式） |
| `GET` | `/applications/{app_id}/incremental/execute-stream` | 流式执行增量更新（SSE） |
| `GET` | `/applications/{app_id}/incremental/remote-data` | 获取平台远程数据 |

### 请求/响应模型

#### DiffRequest

```typescript
interface DiffRequest {
  new_config: Record<string, any>  // 新配置 JSON
}
```

#### DiffResponse

```typescript
interface DiffResponse {
  has_changes: boolean
  summary: string                    // "2个角色变更, 3个字典变更"
  role_changes: ChangeItem[]
  dict_changes: DictChange[]
  model_changes: ModelChange[]
  form_changes: FormChange[]
  process_changes: ProcessChange[]
  warnings: string[]
  unsupported_changes: string[]
}
```

#### ChangeItem

```typescript
interface ChangeItem {
  name: string
  code: string
  change_type: 'added' | 'modified' | 'deleted'
  remote_id?: string                 // 平台资源 ID
  old_value?: Record<string, any>    // 旧版本数据
  new_value?: Record<string, any>    // 新版本数据
}
```

#### ExecuteResponse

```typescript
interface ExecuteResponse {
  success: boolean
  results: {
    roles: string[]
    dicts: string[]
    models: string[]
    forms: string[]
    processes: string[]
  }
  errors: string[]
  warnings: string[]
}
```

#### StreamProgressEvent

```typescript
interface StreamProgressEvent {
  stage?: 'init' | 'roles' | 'dicts' | 'models' | 'forms' | 'processes'
  status?: 'running' | 'done'
  step?: string                      // 当前步骤描述
  current?: number                   // 当前进度
  total?: number                     // 总数
  detail?: string                    // 额外详情（如父资源名称）
  type?: 'complete' | 'error'
  message?: string                   // 错误消息
  result?: ExecuteResponse           // 完成时的结果
}
```

---

## 关键文件索引

| 文件路径 | 职责 |
|----------|------|
| `frontend/src/api/incremental.ts` | 前端 API 封装，SSE 连接管理 |
| `frontend/src/views/ChatPage.vue` | 页面组件，调用增量更新 |
| `frontend/src/components/ConfigDiff.vue` | 差异展示组件 |
| `frontend/src/components/SideBySideDiff.vue` | 并排对比组件 |
| `frontend/src/components/UpdateSteps.vue` | 更新进度展示组件 |
| `backend/app/routes/incremental_update.py` | 后端 API 路由 |
| `backend/app/config_diff.py` | 配置差异计算逻辑 |
| `backend/app/incremental_executor.py` | 增量执行器，调用平台 API |
| `backend/app/apaas_client.py` | 得帆云平台 API 客户端 |

### 代码定位

| 功能 | 文件:行号 |
|------|-----------|
| SSE 连接建立 | `frontend/src/api/incremental.ts:145-207` |
| SSE 端点处理 | `backend/app/routes/incremental_update.py:227-361` |
| 差异计算入口 | `backend/app/config_diff.py:compute_config_diff()` |
| 流式执行入口 | `backend/app/incremental_executor.py:execute_diff_stream()` |
| 远程数据获取 | `backend/app/incremental_executor.py:fetch_remote_data()` |

---

## 错误处理

### 常见错误场景

| 错误 | 原因 | 处理方式 |
|------|------|----------|
| 401 Unauthorized | token 无效或过期 | 前端重新登录 |
| 400 未连接得帆云平台 | 用户未配置 APaaS token | 提示用户去设置页连接 |
| 400 应用尚未在平台创建 | app.apaas_app_id 为空 | 需要先完成首次生成 |
| 500 获取平台数据失败 | APaaS API 调用失败 | 检查网络或 token 有效性 |
| 500 增量更新执行失败 | 单个资源创建/更新失败 | 记录 errors，继续执行其他 |

### 错误恢复

增量更新支持部分成功：
- 单个资源失败不会中断整体流程
- 失败的资源记录在 `errors` 数组中
- 成功的资源记录在 `results` 中
- 前端可根据 `success` 字段判断是否全部成功

```typescript
if (result.success) {
  showSuccess('增量更新完成')
} else {
  showWarning(`部分更新成功，${result.errors.length} 个错误`)
  result.errors.forEach(err => console.error(err))
}
```

---

## 扩展说明

### 新增资源类型

如需支持新的资源类型（如"菜单"），需要：

1. **config_diff.py**: 添加 `MenuChange` 类和差异检测逻辑
2. **incremental_executor.py**: 添加 `_execute_menu_change()` 方法
3. **incremental_update.py**: 更新响应模型
4. **incremental.ts**: 更新 TypeScript 类型
5. **ConfigDiff.vue**: 添加菜单变更展示区块

### 性能优化建议

1. **批量操作**: 平台 API 支持批量时，合并请求减少网络开销
2. **并行执行**: 同类型资源间无依赖时可并行创建
3. **增量缓存**: 缓存 remote_data 减少重复获取

---

*文档版本: 1.0*
*更新日期: 2024-03*

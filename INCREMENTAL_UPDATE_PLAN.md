# 增量更新资源实现计划

## 需求背景

用户在同一会话中上传文档创建应用后，文档有修改时，希望：
1. 不重新创建应用
2. 直接更新现有资源（角色、字典、模型、表单等）

## 当前限制

### 平台 API 限制（关键约束）

> **待补充**：请在下方添加得帆 APaaS 平台的更新、删除、查询接口信息

| 资源类型 | 创建 | 查询 | 更新 | 删除/禁用 |
|---------|------|------|------|----------|
| 角色 | ✅ | ✅ | ✅ | ✅ 删除 |
| 字典 | ✅ | ✅ | ✅ | ⚠️ 禁用 |
| 字典选项 | ✅ | ✅ | ✅ | ⚠️ 禁用 |
| 模型 | ✅ | ✅ | ✅ | ❌ 废弃 |
| 模型字段 | ✅ | ✅ | ✅ | ⚠️ 更新状态 |
| 表单配置 | ✅ | ✅ | ✅ | ✅ 删除 |
| 流程配置 | ✅ | ✅ | ✅ | ⚠️ 关闭 |

### 得帆 APaaS 平台接口补充

#### 角色管理
- 查询角色列表：`POST /xdap-app/roles/query/rolesList`
- 创建角色：`POST /xdap-app/common/resource/appRole`
- 更新角色：`POST /xdap-app/roles/edit/role`
- 删除角色：`POST /xdap-app/roles/delete/role`

#### 字典管理
- 查询字典列表：`POST /xdap-app/dataDictionary/query/dataDictionaryList`
- 创建字典：`POST /xdap-app/common/resource/appDict`
- 更新字典：`POST /xdap-app/dataDictionary/edit/dataDictionary/fromApp`
- 启用字典：`GET /xdap-app/dataDictionary/enable/dataDictionary?id={id}`
- 禁用字典：`GET /xdap-app/dataDictionary/disable/dataDictionary?id={id}`

#### 字典值管理
- 查询字典值：`POST /xdap-app/dataDictionary/query/dictionaryValueList`
- 新增字典值：`POST /xdap-app/dataDictionary/add/dictionaryValue`
- 更新字典值：`POST /xdap-app/dataDictionary/edit/dictionaryValue/fromApp`
- 启用字典值：`GET /xdap-app/dataDictionary/enable/dictionaryValue?id={id}`
- 禁用字典值：`GET /xdap-app/dataDictionary/disable/dictionaryValue?id={id}`

#### 模型管理
- 查询模型(含字段)：`POST /xdap-app/dataModel/query/modelWithField`
- 分页查询模型：`POST /xdap-app/dataModel/query/list`
- 创建模型：`POST /xdap-app/common/resource/v2/appModel`
- 更新模型：`POST /xdap-app/dataModel/update`
- 删除模型：❌ 不支持（直接废弃，不做处理）

#### 模型字段管理
- 分页查询字段：`POST /xdap-app/modelField/query`
- 新增字段：`POST /xdap-app/modelField/add`
- 更新字段：`POST /xdap-app/modelField/update/fromApp`
- 批量更新字段：`POST /xdap-app/modelField/batchUpdate`
- 禁用字段：通过更新接口设置 `fieldStatus: "DISABLE"`

#### 表单管理
- 删除表单：`POST /xdap-app/menu/delete/menu`

#### 流程管理
- 关闭流程：`POST /xdap-app/process/close/processConfig?processId={id}&timestamp={ts}`

---

### 已有的复用机制
- 字典选项：支持 merge 模式（跳过已有，添加新增）
- 模型/字典/表单：按名称检测，跳过已存在

### 关联规则

1. 角色使用角色名称roleName进行关联
2. 字典、字典选项使用 dictionaryCode、 valueCode进行关联
3. 模型、字段使用 modelCode 进行关联
4. 表单组件通过 modelField 进行关联，子表通过tableModelCode进行关联，子表内组件通过 modelField 进行关联

---

## 实现方案

### 核心设计：差异检测 + 增量执行

```
新配置 ──┐
         ├─→ compute_diff() ─→ ConfigDiff ─→ IncrementalExecutor ─→ 平台 API
旧配置 ──┘
```

### 更新策略矩阵

> **注意**：此矩阵需要根据补充的 API 能力重新评估

| 变更类型 | 角色 | 字典 | 字典选项 | 模型 | 模型字段 | 表单组件 | 流程 |
|---------|------|------|---------|------|---------|---------|------|
| 新增 | ✅ 创建 | ✅ 创建 | ✅ 添加 | ✅ 创建 | ✅ 添加 | ✅ 更新 | ✅ 更新 |
| 修改 | ✅ 更新 | ✅ 更新 | ✅ 更新 | ✅ 更新 | ✅ 更新 | ✅ 更新 | ✅ 更新 |
| 删除 | ✅ 删除 | ⚠️ 禁用 | ⚠️ 禁用 | ❌ 废弃 | ⚠️ 更新状态 | ✅ 移除 | ⚠️ 关闭 |

**删除策略说明：**
- ✅ 删除：直接调用删除接口
- ⚠️ 禁用：调用禁用接口代替删除（保留数据完整性）
- ⚠️ 更新状态：通过更新接口将 `fieldStatus` 设为 `DISABLE`
- ⚠️ 关闭：流程使用关闭接口代替删除
- ❌ 废弃：平台不支持删除，直接忽略（模型保留在平台中）

---

## 文件变更

### 新增文件

#### 1. `backend/app/config_diff.py` - 配置差异检测
```python
@dataclass
class ConfigDiff:
    has_changes: bool
    role_changes: List[RoleChange]
    dict_changes: List[DictChange]
    model_changes: List[ModelChange]
    warnings: List[str]
    unsupported_changes: List[str]

def compute_config_diff(old_config: dict, new_config: dict) -> ConfigDiff:
    """对比新旧配置，生成差异报告"""
```

#### 2. `backend/app/incremental_executor.py` - 增量执行器
```python
class IncrementalExecutor:
    async def execute_diff(self, diff: ConfigDiff) -> dict:
        """执行差异更新"""
        # 1. 新增角色
        # 2. 新增/更新字典选项
        # 3. 新增模型
        # 4. 更新表单组件
        # 5. 更新流程配置
```

#### 3. `backend/app/routes/incremental_update.py` - 增量更新路由
```python
@router.post("/applications/{app_id}/incremental/diff")
async def compute_diff(...) -> DiffResponse

@router.post("/applications/{app_id}/incremental/preview")
async def preview_update(...) -> UpdatePreviewResponse

@router.post("/applications/{app_id}/incremental/execute")
async def execute_update(...) -> UpdateExecuteResponse
```

### 修改文件

#### 4. `backend/app/main.py`
- 注册 incremental_update 路由

#### 5. `backend/app/routes/applications.py`
- PUT `/{app_id}` 接口添加 `incremental: bool` 参数

---

## API 设计

### POST `/applications/{app_id}/incremental/diff`
对比新旧配置，返回差异报告

**请求：**
```json
{
  "new_config": { "data": { "models": [...], "dicts": [...] } }
}
```

**响应：**
```json
{
  "has_changes": true,
  "summary": "新增 2 个角色；修改 1 个字典",
  "role_changes": [{ "name": "审批人", "change_type": "added" }],
  "dict_changes": [{ "name": "状态", "change_type": "modified", "option_changes": [...] }],
  "warnings": ["字典「状态」选项删除不会从平台移除"],
  "unsupported_changes": ["模型「旧模型」删除：平台不支持"]
}
```

### POST `/applications/{app_id}/incremental/execute`
执行增量更新

**响应：**
```json
{
  "success": true,
  "results": {
    "roles": ["新增角色: 审批人"],
    "dicts": ["字典 状态: 新增 3 个选项"],
    "forms": ["更新表单: 订单"]
  },
  "errors": []
}
```

---

## 用户交互流程

```
1. 用户上传修改后的文档
       ↓
2. 前端调用 /diff 获取差异
       ↓
3. 展示差异对比界面
   - 新增（绿色）/ 修改（黄色）/ 删除（红色+警告）
       ↓
4. 用户确认后调用 /execute
       ↓
5. 展示执行结果
```

---

## 实现步骤

### Phase 1: 配置差异检测（1-2 天）
- [ ] 创建 `config_diff.py`
- [ ] 实现 `compute_config_diff()` 函数
- [ ] 实现各资源类型的差异检测
- [ ] 添加单元测试

### Phase 2: 增量执行器（2-3 天）
- [ ] 创建 `incremental_executor.py`
- [ ] 实现角色增量创建
- [ ] 实现字典选项增量添加
- [ ] 实现表单组件更新
- [ ] 实现流程配置更新

### Phase 3: API 路由（1 天）
- [ ] 创建 `routes/incremental_update.py`
- [ ] 实现 `/diff`、`/preview`、`/execute` 接口
- [ ] 注册路由到 main.py
- [ ] 修改现有 PUT 接口

### Phase 4: 前端实现（2-3 天）

#### 新增文件

**`frontend/src/components/ConfigDiff.vue`** - 配置差异对比组件
```vue
<template>
  <div class="config-diff">
    <div class="diff-header">
      <span>配置变更：{{ summary }}</span>
    </div>
    <div class="diff-list">
      <div v-for="change in changes" :key="change.key" :class="['diff-item', change.type]">
        <el-tag :type="tagType(change.type)">{{ change.type === 'added' ? '新增' : change.type === 'modified' ? '修改' : '删除' }}</el-tag>
        <span>{{ change.resource }}：{{ change.name }}</span>
        <span v-if="change.warning" class="warning">⚠️ {{ change.warning }}</span>
      </div>
    </div>
  </div>
</template>
```

**`frontend/src/components/UpdateSteps.vue`** - 更新步骤预览
```vue
<template>
  <el-steps :active="currentStep" direction="vertical">
    <el-step v-for="step in steps" :key="step.key" :title="step.label" :status="step.status" />
  </el-steps>
  <el-button type="primary" :loading="executing" @click="execute">执行更新</el-button>
</template>
```

**`frontend/src/api/incremental.ts`** - 增量更新 API
```typescript
export const computeDiff = (appId: number, newConfig: object) =>
  request.post(`/applications/${appId}/incremental/diff`, { new_config: newConfig })

export const previewUpdate = (appId: number, newConfig: object) =>
  request.post(`/applications/${appId}/incremental/preview`, { new_config: newConfig })

export const executeUpdate = (appId: number, newConfig: object) =>
  request.post(`/applications/${appId}/incremental/execute`, { new_config: newConfig })
```

#### 修改文件

**`frontend/src/views/ChatPage.vue`**
- 检测已有应用时，调用 `/diff` 对比变更
- 展示 ConfigDiff 组件
- 替换"创建应用"为"更新应用"按钮

**`frontend/src/views/Generate.vue`**
- 增量模式下展示 UpdateSteps 组件
- 执行进度展示

### Phase 5: 测试验证（1 天）
- [ ] 后端单元测试
- [ ] 前端组件测试
- [ ] 端到端测试
- [ ] 边界情况处理

---

## 验证方法

1. **单元测试**：`pytest backend/tests/test_config_diff.py`
2. **接口测试**：
   ```bash
   # 获取差异
   curl -X POST http://localhost:8001/api/applications/1/incremental/diff \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"new_config": {...}}'

   # 执行更新
   curl -X POST http://localhost:8001/api/applications/1/incremental/execute \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"new_config": {...}}'
   ```
3. **手动验证**：
   - 上传文档创建应用
   - 修改文档后再次上传
   - 检查平台资源是否正确增量更新

---

## 决策确认

- **平台 API**：基于现有 API 实现，不支持的操作标记为警告
- **删除策略**：删除操作仅从配置移除，不从平台删除（避免数据丢失）
- **实现范围**：前后端一起实现

---

## 待完善内容

~~补充得帆 APaaS 接口后，需要更新：~~
~~1. 更新"平台 API 限制"表格中的 ✅/❌ 标记~~
~~2. 更新"更新策略矩阵"中的支持情况~~
3. 在 `apaas_client.py` 中添加新的 API 方法
4. 调整 `incremental_executor.py` 中的执行逻辑

> ✅ 已完成：平台 API 接口信息和更新策略矩阵已根据 `.claude/skills/` 目录下的技能文档补充完善。

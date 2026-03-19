# aPaaS Builder AI 改进计划

## 当前问题分析

### 1. 前端对话框 → 后端生成流程的问题

**现状：**
- ✅ 前端有对话界面（`/chat/send`）
- ✅ 可以上传文档解析（`/upload-doc`）
- ✅ 可以生成应用（`/generate`）
- ❌ **但是** 生成流程使用的是旧的 `generator.py`，功能不完整

**旧版 generator.py 的问题：**
1. ❌ 只创建空字典，没有添加选项
2. ❌ 没有正确绑定下拉选择组件到数据字典
3. ❌ 没有保存进度文件（app_id, suffix, code 映射）
4. ❌ 缺少错误处理和重试机制
5. ❌ 没有利用我们新封装的 `apaas_client.py` 方法

**新版 generator_v2.py 的改进：**
1. ✅ 完整的 5 阶段流程（遵循 Skills 文档）
2. ✅ 创建字典并添加选项
3. ✅ 正确绑定下拉选择组件到数据字典（使用 `source` 和 `chooseOptions`）
4. ✅ 保存进度文件，便于后续添加功能
5. ✅ 使用封装好的 `apaas_client.py` 方法
6. ✅ 详细的进度提示和错误处理

### 2. Skills 知识库未被利用

**现状：**
- ✅ 我们创建了 35+ 个 Skills 文档
- ✅ 文档包含完整的 API 使用方法和最佳实践
- ❌ **但是** 这些文档只有 Claude Code (CLI) 在用
- ❌ Web 应用的生成流程没有参考这些文档

**改进方向：**
- 让 Web 应用的生成器也遵循 Skills 文档中的流程
- 或者让 LLM 在生成配置时参考 Skills 文档

### 3. 工具封装未被充分利用

**现状：**
- ✅ `apaas_client.py` 已封装核心方法
- ❌ 但 `generator.py` 还在直接调用底层 API
- ❌ 没有复用封装好的方法

**改进：**
- 使用 `client.query_dicts()` 而不是手写 httpx 请求
- 使用 `client.add_dict_option()` 而不是重复构造 payload
- 使用 `client.update_form_component()` 更新表单

## 改进方案

### 方案 1：替换生成器（推荐）

**步骤：**
1. 将 `applications.py` 中的 `generator.py` 替换为 `generator_v2.py`
2. 测试完整的应用生成流程
3. 验证字典选项、表单组件绑定是否正确

**优点：**
- 立即见效
- 功能完整
- 代码可维护

**实施：**
```python
# backend/app/routes/applications.py
# 修改导入
from app.generator_v2 import run_complete_generation

# 修改 /generate 接口
async for event in run_complete_generation(client, app_id, config_preview):
    yield event
```

### 方案 2：让 LLM 参考 Skills 生成配置（长期）

**思路：**
- 在 `chat.py` 的 system prompt 中加入 Skills 文档的关键内容
- 或者让 LLM 在生成配置前先读取相关 Skills 文档
- 生成的配置更符合最佳实践

**优点：**
- LLM 生成的配置更准确
- 减少后期修正工作

**挑战：**
- Skills 文档较多，如何有效注入到 prompt
- 可能需要 RAG（检索增强生成）

### 方案 3：添加"添加功能"接口

**需求：**
用户在已有应用中添加新功能（新表单、新字典、新角色）

**实施：**
```python
# 新增接口
@router.post("/{app_id}/add-feature")
async def add_feature(
    app_id: str,
    feature_config: dict,  # 新功能的配置
    ctx: AuthContext
):
    """在已有应用中添加新功能"""
    # 1. 加载应用的 progress（app_id, suffix, code 映射）
    # 2. 调用 add_new_dicts, add_new_models, add_new_forms
    # 3. 更新 progress
    pass
```

**参考：**
- `skills/apaas-add-feature.md`

## 具体改进任务

### 任务 1：替换生成器 ⭐ 优先级高
- [ ] 修改 `applications.py` 导入 `generator_v2`
- [ ] 测试完整流程
- [ ] 验证字典选项是否正确添加
- [ ] 验证下拉选择是否正确绑定字典

### 任务 2：完善 apaas_client.py
- [ ] 添加 `create_dict_with_options()` 方法（一次性创建字典和选项）
- [ ] 添加 `bind_component_to_dict()` 方法（绑定组件到字典）
- [ ] 添加 `add_form_component()` 方法（添加新组件到表单）

### 任务 3：添加进度管理
- [ ] 在数据库中保存应用的 progress（suffix, code 映射）
- [ ] 提供 `/applications/{app_id}/progress` 接口查询进度
- [ ] 在添加功能时自动加载 progress

### 任务 4：添加"添加功能"接口
- [ ] 实现 `POST /applications/{app_id}/add-feature`
- [ ] 支持添加新字典、新角色、新模型、新表单
- [ ] 支持更新已有表单（添加字段）

### 任务 5：改进 LLM 配置生成
- [ ] 在 system prompt 中加入关键的 Skills 知识
- [ ] 或者实现 RAG，让 LLM 检索相关 Skills 文档
- [ ] 生成的配置包含完整的字典选项

### 任务 6：添加配置验证
- [ ] 验证字典选项是否完整
- [ ] 验证模型引用是否正确
- [ ] 验证表单组件配置是否完整

### 任务 7：改进错误处理
- [ ] 字典重复时自动跳过或更新
- [ ] 角色重复时自动跳过
- [ ] 模型创建失败时提供详细错误信息

### 任务 8：添加测试
- [ ] 端到端测试：上传文档 → 生成应用 → 验证结果
- [ ] 单元测试：各个生成阶段的测试
- [ ] 集成测试：与 aPaaS 平台的集成测试

## 实施优先级

### P0 - 立即实施（本周）
1. ✅ 创建 `generator_v2.py`
2. ⬜ 替换 `applications.py` 中的生成器
3. ⬜ 测试完整流程

### P1 - 短期实施（2周内）
4. ⬜ 完善 `apaas_client.py` 方法
5. ⬜ 添加进度管理
6. ⬜ 添加"添加功能"接口

### P2 - 中期实施（1个月内）
7. ⬜ 改进 LLM 配置生成
8. ⬜ 添加配置验证
9. ⬜ 改进错误处理

### P3 - 长期实施（持续）
10. ⬜ 添加完整的测试覆盖
11. ⬜ 性能优化
12. ⬜ 文档完善

## 预期效果

**改进前：**
- 用户上传文档 → 生成应用 → 字典没有选项 ❌
- 下拉选择显示"输入值"而不是"数据字典" ❌
- 无法在已有应用中添加新功能 ❌

**改进后：**
- 用户上传文档 → 生成应用 → 字典包含完整选项 ✅
- 下拉选择正确绑定到数据字典 ✅
- 可以在已有应用中添加新功能 ✅
- 保存进度，便于后续操作 ✅

## 总结

核心思想：**不要重复造轮子，复用 Skills 和 Tools**

1. Skills 文档 = 知识库（如何做）
2. apaas_client.py = 工具箱（封装好的方法）
3. generator_v2.py = 编排器（按照 Skills 调用 Tools）
4. Web 应用 = 用户界面（调用编排器）

这样整个系统就形成了一个完整的闭环！

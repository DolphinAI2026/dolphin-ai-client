# aPaaS Builder AI - 项目结构说明

## 项目概述
基于 AI 的低代码平台应用生成器，用于自动化创建得帆云 aPaaS 平台应用。

## 目录结构

```
apaas-builder-ai/
├── backend/                    # 后端服务（FastAPI）
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI 应用入口
│   │   ├── config.py          # 配置管理
│   │   ├── database.py        # 数据库连接
│   │   ├── deps.py            # 依赖注入
│   │   ├── auth.py            # 认证逻辑
│   │   ├── permissions.py     # 权限管理
│   │   ├── schemas.py         # Pydantic 数据模型
│   │   │
│   │   ├── apaas_client.py    # ★ aPaaS API 客户端（核心）
│   │   ├── config_transformer.py  # 配置转换器
│   │   ├── doc_parser.py      # 文档解析器
│   │   ├── generator.py       # 应用生成器
│   │   ├── llm_client.py      # LLM 客户端
│   │   │
│   │   ├── models/            # 数据库模型
│   │   │   ├── __init__.py
│   │   │   └── tenant.py
│   │   │
│   │   ├── routes/            # API 路由
│   │   │   ├── __init__.py
│   │   │   ├── apaas.py       # aPaaS 相关接口
│   │   │   ├── applications.py
│   │   │   ├── auth.py
│   │   │   ├── chat.py
│   │   │   └── conversations.py
│   │   │
│   │   └── skills/            # Skills 编排（旧版）
│   │       ├── __init__.py
│   │       ├── components.py
│   │       ├── orchestrator.py
│   │       └── platform.py
│   │
│   ├── .env                   # 环境变量配置
│   ├── requirements.txt       # Python 依赖
│   ├── run.py                # 启动脚本
│   └── apaas_builder.db      # SQLite 数据库
│
├── frontend/                  # 前端（Vue.js）
│   ├── src/
│   ├── package.json
│   └── README.md
│
├── skills/                    # ★ Skills 知识库（核心）
│   ├── README.md             # Skills 使用说明
│   │
│   ├── apaas-create-complete-app.md  # ★ 完整应用创建流程
│   ├── apaas-add-feature.md          # ★ 添加新功能流程
│   │
│   ├── apaas-create-app.md           # 创建应用
│   ├── apaas-create-dict.md          # 创建数据字典
│   ├── apaas-create-model.md         # 创建数据模型
│   ├── apaas-create-role.md          # 创建角色
│   ├── apaas-create-form.md          # 创建表单
│   │
│   ├── apaas-query-dict.md           # 查询数据字典
│   ├── apaas-query-model.md          # 查询数据模型
│   ├── apaas-query-role.md           # 查询角色
│   ├── apaas-query-form.md           # 查询表单
│   │
│   ├── apaas-update-app.md           # 更新应用
│   ├── apaas-update-dict.md          # 更新数据字典
│   ├── apaas-update-role.md          # 更新角色
│   ├── apaas-update-form.md          # ★ 更新表单（含字典绑定）
│   ├── apaas-add-field.md            # 添加字段
│   │
│   └── apaas-comp-*.md               # 各种表单组件配置
│       ├── apaas-comp-text.md
│       ├── apaas-comp-select-single.md
│       ├── apaas-comp-data-selector.md
│       ├── apaas-comp-son-table.md
│       └── ... (共 15 个组件文档)
│
├── scripts/                   # 脚本工具
│   ├── gen_afterservice.py   # 生成售后系统
│   ├── gen_curl_payloads.py  # 生成 curl 测试
│   ├── test_complex_form.py  # 测试复杂表单
│   ├── test_full_deploy.py   # 测试完整部署
│   └── afterservice_config.json
│
├── tests/                     # 测试
│   ├── test_orchestrator_e2e.py
│   ├── test_skills_e2e.py
│   └── test_skills_unit.py
│
├── README.md                  # 项目说明
├── DEVELOPMENT.md            # 开发指南
├── PROJECT_STATUS.md         # 项目状态
├── PROJECT_SUMMARY.md        # 项目总结
└── start.sh                  # 启动脚本
```

## 核心组件说明

### 1. Skills 知识库 (`/skills/`)
**作用**：存储 aPaaS API 的使用文档和最佳实践

**特点**：
- Markdown 格式，易于阅读和维护
- 包含 API 端点、请求格式、响应格式、Python 示例
- 记录了实际使用中遇到的问题和解决方案
- AI 通过读取这些文档来学习如何操作 aPaaS 平台

**重要文档**：
- `apaas-create-complete-app.md` - 完整应用创建的 5 个阶段
- `apaas-add-feature.md` - 在已有应用中添加新功能
- `apaas-update-form.md` - 表单更新（含下拉选择绑定字典的正确方法）

### 2. aPaaS Client (`backend/app/apaas_client.py`)
**作用**：封装 aPaaS API 调用的 Python 客户端

**核心方法**：

**认证**：
- `login()` - RSA 加密登录

**创建资源**：
- `create_app()` - 创建应用
- `create_dicts()` - 批量创建数据字典
- `create_roles()` - 批量创建角色
- `create_models()` - 批量创建数据模型
- `create_form_config()` - 批量创建表单

**查询资源**：
- `query_app_list()` - 查询应用列表
- `query_dicts()` - 查询数据字典
- `query_dict_options()` - 查询字典选项
- `query_menus()` - 查询菜单（含表单）
- `query_form_config()` - 查询表单配置

**更新资源**：
- `add_dict_option()` - 添加字典选项
- `save_form_config()` - 保存表单配置
- `update_form_component()` - 更新表单组件

### 3. Config Transformer (`backend/app/config_transformer.py`)
**作用**：将简化的配置格式转换为 aPaaS API 所需的完整格式

**主要功能**：
- 自动生成随机后缀避免命名冲突
- 处理字段类型映射
- 构建复杂的组件配置结构

### 4. 前端 (`/frontend/`)
**作用**：提供 Web UI 界面

**功能**：
- 应用管理
- 对话式应用生成
- 配置预览和编辑

## 工作流程

### 创建新应用的流程
```
1. 用户提供需求文档
   ↓
2. AI 读取 skills/apaas-create-complete-app.md
   ↓
3. Phase 1: 创建应用（apaas_client.create_app）
   ↓
4. Phase 2: 创建数据字典 + 添加选项
   ↓
5. Phase 3: 创建角色
   ↓
6. Phase 4: 创建数据模型
   ↓
7. Phase 5: 创建表单
   ↓
8. 保存进度到 /tmp/xxx_results.json
```

### 添加新功能的流程
```
1. 加载已有应用信息（app_id, suffix）
   ↓
2. AI 读取 skills/apaas-add-feature.md
   ↓
3. 添加新的数据字典/角色/模型/表单
   ↓
4. 更新进度文件
```

### 更新表单组件的流程
```
1. 查询表单配置（query_form_config）
   ↓
2. 修改组件属性
   ↓
3. 保存表单配置（save_form_config）
```

## 关键经验总结

### 1. 下拉选择绑定数据字典
必须设置以下字段：
```python
component['source'] = {
    "type": "DICTIONARY_TYPE",
    "id": dict_id  # 字典的数据库 ID
}
component['chooseOptions'] = [...]
component['dictionaryChooseOptions'] = [...]
```

### 2. 命名规范
- 应用编码：`app-name-{suffix}` (使用连字符，不用下划线)
- 字典编码：`dict_code_{suffix}`
- 角色编码：`R_{role_code}_{suffix}`
- 模型编码：`Model_{suffix}`
- 表单编码：`form_{name}_{suffix}`

### 3. 进度管理
使用 JSON 文件保存创建进度：
```json
{
  "app_id": "...",
  "suffix": "...",
  "dict_codes": {...},
  "role_codes": {...},
  "model_codes": {...}
}
```

## 技术栈

**后端**：
- Python 3.9+
- FastAPI
- SQLAlchemy
- httpx (HTTP 客户端)
- cryptography (RSA 加密)

**前端**：
- Vue.js 3
- TypeScript
- Vite

**aPaaS 平台**：
- 得帆云 aPaaS
- API Base: https://apaas-poc.definesys.cn/backend

## 开发建议

1. **添加新功能时**：
   - 先在 `/skills/` 中创建或更新文档
   - 然后在 `apaas_client.py` 中添加对应的方法
   - 最后编写测试验证

2. **遇到 API 问题时**：
   - 记录到对应的 skill 文档中
   - 更新"注意事项"和"常见错误"章节

3. **保持一致性**：
   - 使用统一的命名后缀
   - 保存进度文件便于后续操作
   - 复用已有的 dict_codes、model_codes 映射

## 下一步计划

- [ ] 完善表单权限配置
- [ ] 添加流程配置支持
- [ ] 实现表单间的数据联动
- [ ] 支持子表和复杂组件
- [ ] 添加更多测试用例

# aPaaS Builder - 标准化工具链

## 概述

这是一套标准化的 aPaaS 应用构建工具链，将 AI 和执行引擎分离：

- **AI 层**：理解需求，生成标准 YAML 配置（不写执行代码）
- **执行层**：稳定的 Python 引擎，解析配置并调用 API

## 架构

```
用户需求
   ↓
AI 生成 YAML 配置（简单，不易出错）
   ↓
执行引擎解析配置（稳定可靠）
   ↓
调用 aPaaS API
   ↓
创建完整应用
```

## 核心文件

### 1. 配置 Schema
**文件**: `backend/app/app_config_schema.py`

定义标准配置格式，包含：
- `AppConfig` - 应用配置
- `DictConfig` - 数据字典
- `ModelConfig` - 数据模型
- `FormConfig` - 表单配置
- Pydantic 验证

### 2. 执行引擎
**文件**: `backend/app/app_executor.py`

负责执行配置：
- `AppExecutor.execute()` - 主入口
- Phase 1: 创建应用
- Phase 2: 创建数据字典
- Phase 3: 创建数据模型
- Phase 4: 创建表单
- 自动处理保留字、后缀、错误重试

### 3. CLI 工具
**文件**: `backend/apaas_builder_cli.py`

命令行工具：
```bash
# 验证配置
apaas-builder validate config.yaml

# 创建应用
apaas-builder create config.yaml -a account -p password

# 生成模板
apaas-builder init my_app.yaml

# 查看示例
apaas-builder example
```

### 4. Skills（AI 指南）
**文件**: `~/.claude/skills/apaas/apaas-app-builder.md`

教 AI 如何生成配置文件：
- 配置格式说明
- 字段类型映射
- 完整示例
- 编码规则

## 使用流程

### 方式 1: 通过 AI 生成配置

```bash
# 在 apaas-builder-ai 项目中
cd /Users/mars/Vibe\ Coding/apaas-builder-ai

# 对 AI 说："创建一个资产管理系统，包含..."
# AI 会生成 asset_management.yaml

# 验证配置
python backend/apaas_builder_cli.py validate asset_management.yaml

# 执行创建
python backend/apaas_builder_cli.py create asset_management.yaml \
  --account 17621440039 \
  --password definesys2019
```

### 方式 2: 手动编写配置

```bash
# 生成模板
python backend/apaas_builder_cli.py init my_app.yaml

# 编辑 my_app.yaml

# 验证
python backend/apaas_builder_cli.py validate my_app.yaml

# 创建
python backend/apaas_builder_cli.py create my_app.yaml -a account -p password
```

### 方式 3: 在 MarsAgent 中集成

```python
from app.apaas_client import APaaSClient
from app.app_executor import AppExecutor
from app.app_config_schema import AppConfig
import yaml

# 1. AI 生成配置
config_yaml = """
name: 资产管理系统
dicts: [...]
models: [...]
forms: [...]
"""

# 2. 解析配置
config_data = yaml.safe_load(config_yaml)
config = AppConfig(**config_data)

# 3. 执行创建
client = APaaSClient()
await client.login(account, password)

executor = AppExecutor(client)
progress = await executor.execute(config)

print(f"应用创建成功: {progress['app_id']}")
```

## 配置示例

完整示例见：`examples/asset_management.yaml`

```yaml
name: 资产管理系统
description: 企业资产管理应用

dicts:
  - name: 资产类别
    code: asset_category
    options:
      - {name: 电子设备, code: electronic}
      - {name: 办公家具, code: furniture}

models:
  - name: 资产
    code: asset
    fields:
      - {name: 资产名称, code: asset_name, type: 单行输入, required: true}
      - {name: 资产类别, code: category, type: 下拉单选, dict: asset_category}

forms:
  - name: 资产
    model: asset
    components:
      - {field: asset_name, required: true}
      - {field: category}
```

## 优势

### 对比旧方案（生成 Python 代码）

| 维度 | 旧方案 | 新方案 |
|------|--------|--------|
| AI 任务 | 生成完整 Python 代码 | 生成简单 YAML 配置 |
| 出错概率 | 高（代码复杂） | 低（配置简单） |
| 可维护性 | 差（每次都是新代码） | 好（执行引擎统一维护） |
| 适用性 | 仅限能执行代码的 AI | 任何 AI（Dify、MarsAgent 等） |
| 错误处理 | 每次都要写 | 执行引擎统一处理 |
| 保留字处理 | 容易遗漏 | 自动处理 |

### 关键改进

1. **降低 AI 门槛**：只需生成配置，不需要写复杂的执行代码
2. **提高稳定性**：执行引擎经过测试，统一维护
3. **易于集成**：可集成到 MarsAgent、Dify 等任何平台
4. **易于调试**：配置文件可读性强，易于检查和修改
5. **可复用**：配置文件可以保存、分享、版本控制

## 依赖

```bash
# 安装依赖
pip install pydantic click pyyaml httpx cryptography
```

## 测试

```bash
# 验证示例配置
python backend/apaas_builder_cli.py validate examples/asset_management.yaml

# 创建测试应用
python backend/apaas_builder_cli.py create examples/asset_management.yaml \
  --account YOUR_ACCOUNT \
  --password YOUR_PASSWORD
```

## 下一步

1. **添加更新功能**：支持修改已有应用
2. **批量操作**：支持一次创建多个应用
3. **模板库**：预置常见应用模板
4. **Web UI**：可视化配置编辑器
5. **集成到 MarsAgent**：作为 Tool 或 Agent 使用

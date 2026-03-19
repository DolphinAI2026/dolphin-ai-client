# aPaaS Builder 工具链安装说明

## 快速开始

```bash
cd /Users/mars/Vibe\ Coding/apaas-builder-ai

# 安装依赖（如果还没安装）
pip3 install click pyyaml

# 验证配置
python3 backend/apaas_builder_cli.py validate examples/asset_management.yaml

# 创建应用
python3 backend/apaas_builder_cli.py create examples/asset_management.yaml \
  --account 17621440039 \
  --password definesys2019
```

## 已创建的文件

### 核心代码
- `backend/app/app_config_schema.py` - 配置 Schema（Pydantic 模型）
- `backend/app/app_executor.py` - 执行引擎（调用 aPaaS API）
- `backend/apaas_builder_cli.py` - CLI 工具

### 配置示例
- `examples/asset_management.yaml` - 资产管理系统配置

### 文档
- `TOOLCHAIN.md` - 工具链完整说明

### Skills（全局）
- `~/.claude/skills/apaas/apaas-app-builder.md` - 更新为配置生成模式
- `~/.claude/skills/apaas/apaas-app-updater.md` - 应用更新
- `~/.claude/skills/apaas/apaas-api-reference.md` - API 参考
- `~/.claude/skills/apaas/README.md` - Skills 说明

## 工作流程

### 1. AI 生成配置（在任何项目中）

对 AI 说："创建一个XX系统，包含..."

AI 会生成类似这样的配置：

```yaml
name: XX系统
dicts: [...]
models: [...]
forms: [...]
```

### 2. 保存配置文件

```bash
# 保存到文件
cat > my_app.yaml << 'EOF'
name: XX系统
...
EOF
```

### 3. 验证配置

```bash
python3 backend/apaas_builder_cli.py validate my_app.yaml
```

### 4. 执行创建

```bash
python3 backend/apaas_builder_cli.py create my_app.yaml \
  --account YOUR_ACCOUNT \
  --password YOUR_PASSWORD
```

## 优势总结

**旧方案**：AI 每次生成完整 Python 代码 → 容易出错，难维护

**新方案**：AI 生成简单 YAML 配置 → 执行引擎统一处理 → 稳定可靠

## 下一步测试

```bash
# 1. 安装依赖
pip3 install click pyyaml

# 2. 验证示例配置
python3 backend/apaas_builder_cli.py validate examples/asset_management.yaml

# 3. 创建测试应用（需要真实账号）
python3 backend/apaas_builder_cli.py create examples/asset_management.yaml \
  --account 17621440039 \
  --password definesys2019
```

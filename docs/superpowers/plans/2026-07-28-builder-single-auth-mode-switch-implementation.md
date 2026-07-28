# Builder Config-Driven Auth Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 `AUTH_PROVIDER` 配置文件字段为每个客户实例选择唯一登录模式，并让缺省模式明确为 Control Plane。

**Architecture:** 保留现有 `/auth/login` 和 `/auth/captcha` 对 `AUTH_PROVIDER` 的直接分派，不引入数据库或界面切换。只调整配置默认值、补充行为测试和部署说明；Control Plane 用户绑定 aPaaS 的现有模型与调用链完全不动。

**Tech Stack:** Pydantic Settings、FastAPI、pytest、Docker/Kubernetes 环境变量配置。

---

## 文件结构

- Modify: `backend/app/config.py`
  将 `auth_provider` 缺省值设为 `control_plane`。
- Create: `backend/tests/test_auth_provider_config.py`
  验证缺省值和环境变量覆盖行为。
- Modify: `README.md`
  说明客户级单模式配置、重启生效和 aPaaS 绑定边界。
- Verify: `deploy/customer/backend.env.template`
  保持唯一 `AUTH_PROVIDER` 配置，不新增 UI 或数据库配置。
- Verify: `deploy/customer/deploy.sh`
  保持客户部署只接受 `control_plane|apaas`。

### Task 1: 默认 Control Plane 配置

**Files:**
- Create: `backend/tests/test_auth_provider_config.py`
- Modify: `backend/app/config.py`

- [ ] **Step 1: 写入失败测试**

```python
from app.config import Settings


def test_auth_provider_defaults_to_control_plane(monkeypatch):
    monkeypatch.delenv("AUTH_PROVIDER", raising=False)

    config = Settings(_env_file=None, jwt_secret_key="test-secret")

    assert config.auth_provider == "control_plane"
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest \
  backend/tests/test_auth_provider_config.py::test_auth_provider_defaults_to_control_plane -q
```

Expected: 当前默认值为空字符串，断言失败。

- [ ] **Step 3: 修改默认值**

```python
auth_provider: str = "control_plane"
```

不修改 `_auth_provider()` 的历史别名兼容，也不引入数据库读取。

- [ ] **Step 4: 增加环境变量覆盖测试**

```python
def test_auth_provider_accepts_apaas_from_environment(monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "apaas")

    config = Settings(_env_file=None, jwt_secret_key="test-secret")

    assert config.auth_provider == "apaas"
```

- [ ] **Step 5: 运行配置测试**

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest backend/tests/test_auth_provider_config.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交配置修改**

```bash
git add backend/app/config.py backend/tests/test_auth_provider_config.py
git commit -m "fix(auth): default customer login to control plane"
```

### Task 2: 配置说明

**Files:**
- Modify: `README.md`
- Verify: `deploy/customer/backend.env.template`
- Verify: `deploy/customer/deploy.sh`

- [ ] **Step 1: 补充 README**

在 `AUTH_PROVIDER` 示例后明确：

```text
每个客户实例只能配置一种登录模式：control_plane 或 apaas。
修改配置后需要重启后端服务；登录页和管理端不提供切换入口。
Control Plane 用户仍可单独绑定 aPaaS 账号使用低代码能力。
```

- [ ] **Step 2: 验证客户部署模板和脚本**

```bash
rg -n "AUTH_PROVIDER=control_plane|固定一种|control_plane 或 apaas" \
  deploy/customer/backend.env.template deploy/customer/deploy.sh
```

Expected: 模板默认 Control Plane，脚本拒绝其他客户模式。

- [ ] **Step 3: 提交说明**

```bash
git add README.md docs/superpowers
git commit -m "docs(auth): explain config-driven login mode"
```

### Task 3: 回归验证

**Files:**
- Verify: `backend/tests/test_auth_provider_config.py`
- Verify: `backend/tests/test_auth_provider_modes.py`
- Verify: `backend/tests/test_builder_auth_settings.py`

- [ ] **Step 1: 运行认证回归**

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest \
  backend/tests/test_auth_provider_config.py \
  backend/tests/test_auth_provider_modes.py \
  backend/tests/test_builder_auth_settings.py -q
```

Expected: PASS。

- [ ] **Step 2: 确认没有 UI 改动**

```bash
git diff --name-only main...HEAD | rg '^(frontend|admin-spa)/' && exit 1 || true
```

Expected: 没有输出。

- [ ] **Step 3: 审计最终差异**

```bash
git diff --check
git status --short
git diff --stat main...HEAD
```

Expected: 最终差异只包含配置默认值、测试、README 和本设计/计划。

- [ ] **Step 4: 使用 `agentic-git-sync` 完成默认分支同步**

全部验证通过后，将工作分支安全合入 `main` 并推送 `agent-build-ai/main`；禁止 force push、reset、clean 或覆盖其他工作区改动。

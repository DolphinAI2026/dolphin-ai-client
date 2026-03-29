"""aPaaS Builder 原子能力 Skills 包

每个 Skill 是一个独立的可执行函数，可以单独调用也可以组合使用。

平台基础操作:
    - create_app: 创建应用
    - create_models: 创建数据模型
    - create_dicts: 创建数据字典
    - create_roles: 创建角色
    - create_form: 创建表单配置
    - create_permissions: 配置权限
    - deploy_app: 发布应用

组件构建:
    - build_component: 通用组件构建器（支持所有 16 种组件类型）

编排:
    - run_full_build: 完整构建流程（创建应用 → 角色 → 字典 → 模型 → 表单 → 权限 → 发布）
"""
from app.skills.components import build_component, COMPONENT_REGISTRY
from app.skills.platform import (
    create_app,
    create_models,
    create_dicts,
    create_roles,
    create_form,
    create_permissions,
    deploy_app,
    login,
)
from app.skills.orchestrator import run_full_build

__all__ = [
    "build_component",
    "COMPONENT_REGISTRY",
    "create_app",
    "create_models",
    "create_dicts",
    "create_roles",
    "create_form",
    "create_permissions",
    "deploy_app",
    "login",
    "run_full_build",
]

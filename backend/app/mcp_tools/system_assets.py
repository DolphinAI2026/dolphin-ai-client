"""System-assistant MCP tools for tenant-scoped Code assets.

The sandbox capability pack intentionally exposes only read-only projections.
These tools are different: they run in the Builder backend, resolve the logged-in
user from the trusted MCP identity, and call the management APIs with that
user's own Control Plane / Builder-AI session.  They never use a runtime token.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import weakref
import zipfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml
from sqlalchemy import select

from app.builder_ai_management import _internal_headers, _management_base_url
from app.code_runtime.auth import control_plane_access_token, remote_builder_access_token
from app.code_runtime.service import control_plane_base_url
from app.database import AsyncSessionLocal
from app.mcp_envelope import _err, _ok
from app.models import Project, User
from app.models.collaboration import GitConnection


SYSTEM_ASSET_TOOL_NAMES = frozenset({
    "list_system_assets",
    "get_system_asset",
    "get_system_asset_schema",
    "get_system_asset_creation_examples",
    "get_system_assistant_mcp_contract",
    "create_system_asset",
    "update_system_asset",
    "change_system_asset_status",
    "delete_system_asset",
    "get_environment_capability_config",
    "save_environment_capability_config",
    "delete_environment_capability_config",
    "list_system_deployment_environments",
    "list_environment_infrastructure_schemas",
    "upload_knowledge_document",
    "list_knowledge_documents",
    "get_knowledge_document",
    "delete_knowledge_document",
    "publish_knowledge_document",
    "disable_knowledge_document",
    "reindex_knowledge_document",
    "create_system_skill",
    "list_system_skill_versions",
    "create_system_skill_version",
    "enable_system_skill_version",
    "inspect_system_git_repository",
    "configure_system_git_remote",
    "push_system_git_repository",
    "list_system_git_connections",
    "create_system_asset_starter_repository",
    "create_system_capability_git_repository",
})

_ASSET_TYPES = frozenset({
    "seed_project", "capability", "environment", "knowledge_base", "skill", "mcp_server",
})

# This is the Control Plane's exact APP_RUNTIME schema template
# (CapabilitySchemaPolicy.defaultTemplate).  It is kept here deliberately so
# the assistant can return an actionable contract even when the Control Plane
# is temporarily unavailable.  The two sections are mandatory for every newly
# created APP_RUNTIME capability; ``environment:`` is not a valid replacement.
_CAPABILITY_APP_RUNTIME_SCHEMA_TEMPLATE = """\
environmentInstanceRequired: true
applicationEnvironmentInstanceRequired: false
environmentInstanceSchema:
  scope: environment
  required: []
  properties: {}
applicationEnvironmentInstanceSchema:
  scope: application_environment
  required: []
  properties: {}
"""

_CAPABILITY_APP_RUNTIME_EXTERNAL_PARAMETERS_EXAMPLE = """\
environmentInstanceRequired: true
applicationEnvironmentInstanceRequired: true
environmentInstanceSchema:
  scope: environment
  required: [serviceBaseUrl, serviceToken]
  properties:
    serviceBaseUrl:
      type: string
      format: uri
      scope: environment
      sensitive: false
      title: 服务地址
      ui:
        control: urlInput
    serviceToken:
      type: string
      scope: environment
      sensitive: true
      title: 服务访问凭据
      ui:
        control: secretInput
        writeOnly: true
applicationEnvironmentInstanceSchema:
  scope: application_environment
  required: [projectKey]
  properties:
    projectKey:
      type: string
      scope: application_environment
      sensitive: false
      title: 项目标识
      ui:
        control: textInput
"""

_CAPABILITY_SCHEMA_UI_CONTROLS = frozenset({
    "textInput", "urlInput", "secretInput", "numberInput", "select", "textarea",
})

# These contracts deliberately use the Control Plane's canonical wire values.
# Do not replace them with UI labels or lowercase aliases: the system assistant
# needs a stable answer before it asks the user for confirmation.  The generic
# Builder-AI assets are not included here because their management API does not
# expose a stable public form contract; skill creation has its own typed tools.
_ASSET_FIELD_SCHEMAS: dict[str, dict[str, Any]] = {
    "capability": {
        "schema_source": "Control Plane capability create/update contract",
        "create_fields": [
            {"name": "code", "required": True, "description": "能力机器编码；不使用 capabilityName。"},
            {"name": "name", "required": True, "description": "显示名称。"},
            {"name": "runtimeType", "required": True, "allowed_values": ["AGENT_RUNTIME", "APP_RUNTIME"]},
            {"name": "riskLevel", "required": True, "allowed_values": ["GENERAL", "RESTRICTED"], "description": "新版能力不接受 LOW / low / MEDIUM。"},
            {"name": "status", "required": True, "allowed_values": ["ENABLED", "DISABLED"]},
            {"name": "agentCapabilityKind", "required_when": "runtimeType=AGENT_RUNTIME", "allowed_values": ["MCP", "SKILL"], "forbidden_when": "runtimeType=APP_RUNTIME"},
            {"name": "tagIds", "required": False, "description": "正整数数组。"},
            {
                "name": "yamlSchema",
                "required_when": "runtimeType=APP_RUNTIME",
                "forbidden_when": "runtimeType=AGENT_RUNTIME",
                "description": "APP_RUNTIME 的外部参数定义，必须使用 get_system_asset_schema 返回的双段 YAML：environmentInstanceSchema 和 applicationEnvironmentInstanceSchema。不是 environment:。每个外部参数都要在对应 properties 中声明 type、scope、sensitive、title；必填参数还要写入 required。",
            },
            {"name": "description", "required": False},
            {"name": "metadata", "required": False, "description": "对象；不得放入密钥。"},
            {"name": "skillArtifactUploadId", "required_when": "runtimeType=AGENT_RUNTIME 且 agentCapabilityKind=SKILL"},
            {"name": "mcpConfig", "required_when": "runtimeType=AGENT_RUNTIME 且 agentCapabilityKind=MCP"},
        ],
        "update_fields": [
            "name", "riskLevel", "runtimeType", "agentCapabilityKind", "tagIds", "yamlSchema",
            "status", "description", "metadata", "skillArtifactUploadId", "mcpConfig",
        ],
        "unsupported_fields": ["capabilityName", "entrypoint", "maturity", "summary", "version", "codeContent"],
        "examples": {
            "app_runtime_without_external_parameters": {
                "code": "ht-approval-center", "name": "审批中心", "runtimeType": "APP_RUNTIME",
                "riskLevel": "GENERAL", "status": "DISABLED", "yamlSchema": _CAPABILITY_APP_RUNTIME_SCHEMA_TEMPLATE,
            },
            "app_runtime_with_external_parameters": {
                "code": "ht-approval-center", "name": "审批中心", "runtimeType": "APP_RUNTIME",
                "riskLevel": "GENERAL", "status": "DISABLED", "yamlSchema": _CAPABILITY_APP_RUNTIME_EXTERNAL_PARAMETERS_EXAMPLE,
            },
            "agent_mcp": {
                "code": "approval-center-mcp", "name": "审批中心 MCP", "runtimeType": "AGENT_RUNTIME",
                "agentCapabilityKind": "MCP", "riskLevel": "GENERAL", "status": "DISABLED",
                "mcpConfig": {"configJson": {}},
            },
        },
    },
    "environment": {
        "schema_source": "Control Plane environment create/update contract",
        "create_fields": [
            {"name": "environmentName", "required": True, "aliases": ["name"]},
            {"name": "environmentTier", "required": True, "aliases": ["tier"], "allowed_values": ["DEV", "TEST", "STAGING", "PROD", "CUSTOM"]},
            {"name": "environmentRiskLevel", "required": True, "aliases": ["riskLevel"], "allowed_values": ["GENERAL", "RESTRICTED"]},
            {"name": "status", "required": False, "default": "ENABLED", "allowed_values": ["ENABLED", "DISABLED"]},
            {"name": "description", "required": False},
            {"name": "metadata", "required": False, "description": "对象；不得放入密钥。"},
            {"name": "capabilityInstances", "required": False, "description": "能力实例数组。每项使用 capabilityId、yamlValues（环境范围参数的 YAML 实际值）、description、metadata；yamlValues 的字段必须先按该 capability 的 yamlSchema.environmentInstanceSchema 定义。"},
            {"name": "infrastructureInstances", "required": False, "description": "基础设施数组；具体字段先调用 list_environment_infrastructure_schemas。"},
        ],
        "update_fields": ["environmentName", "environmentTier", "environmentRiskLevel", "status", "description", "metadata", "capabilityInstances", "infrastructureInstances"],
        "examples": {
            "test": {"environmentName": "测试环境", "environmentTier": "TEST", "environmentRiskLevel": "GENERAL", "status": "ENABLED"},
        },
    },
    "seed_project": {
        "schema_source": "Control Plane seed-project create/update contract",
        "create_fields": [
            {"name": "seedName", "required": True},
            {"name": "tagIds", "required": False, "description": "正整数数组。"},
            {"name": "providerProjectId", "required": True, "description": "Git 项目 ID。"},
            {"name": "pathWithNamespace", "required": True, "description": "例如 orcamatrix/approval-center。"},
            {"name": "repositoryUrl", "required": True, "description": "Git 仓库 HTTPS 地址。"},
            {"name": "branch", "required": True, "description": "例如 main。"},
            {"name": "description", "required": False},
        ],
        "update_fields": ["seedName", "tagIds", "providerProjectId", "pathWithNamespace", "repositoryUrl", "branch", "description"],
        "fixed_values": {"provider": "gitlab"},
        "examples": {
            "new_git_seed": {
                "seedName": "订单服务 Java 种子",
                "providerProjectId": "<新建 Git 项目的 ID>",
                "pathWithNamespace": "<平台 Git 组>/order-service-java-seed",
                "repositoryUrl": "https://<git-host>/<平台 Git 组>/order-service-java-seed.git",
                "branch": "main",
                "description": "用于企业订单服务的 Spring Boot 工程起点。",
            },
        },
    },
    "skill": {
        "schema_source": "System Assistant typed Skill tools",
        "create_with": "create_system_skill",
        "create_fields": [
            {"name": "name", "required": True}, {"name": "version", "required": True},
            {"name": "instructions", "required": True}, {"name": "description", "required": False},
        ],
    },
    "knowledge_base": {
        "schema_source": "Builder-AI management API",
        "note": "管理端尚未公开稳定的字段枚举；创建前不得猜测字段，先读取现有资产或使用对应管理表单。",
    },
    "mcp_server": {
        "schema_source": "Builder-AI management API",
        "note": "管理端尚未公开稳定的字段枚举；创建前不得猜测字段，先读取现有资产或使用对应管理表单。",
    },
}

_LOCAL_ENUM_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    "capability": {
        "runtimeType": frozenset({"AGENT_RUNTIME", "APP_RUNTIME"}),
        "riskLevel": frozenset({"GENERAL", "RESTRICTED"}),
        "status": frozenset({"ENABLED", "DISABLED"}),
        "agentCapabilityKind": frozenset({"MCP", "SKILL"}),
    },
    "environment": {
        "environmentTier": frozenset({"DEV", "TEST", "STAGING", "PROD", "CUSTOM"}),
        "environmentRiskLevel": frozenset({"GENERAL", "RESTRICTED"}),
        "status": frozenset({"ENABLED", "DISABLED"}),
    },
}

# A tool-level companion to the asset payload schemas above.  This is kept
# deliberately narrow: only real enums, format constraints and values that
# must be obtained from another MCP are included.  Free text and opaque IDs do
# not gain invented value lists merely to make the response look complete.
_SYSTEM_ASSISTANT_MCP_CONTRACTS: dict[str, dict[str, Any]] = {
    "list_system_assets": {
        "parameters": [{"name": "asset_type", "required": True, "allowed_values": sorted(_ASSET_TYPES)}],
    },
    "get_system_asset": {
        "parameters": [
            {"name": "asset_type", "required": True, "allowed_values": sorted(_ASSET_TYPES)},
            {"name": "asset_id", "required": True, "description": "从 list_system_assets 的结果选择。"},
        ],
    },
    "get_system_asset_schema": {
        "parameters": [
            {"name": "asset_type", "required": True, "allowed_values": sorted(_ASSET_TYPES)},
            {"name": "runtime_type", "required": False, "allowed_values": ["AGENT_RUNTIME", "APP_RUNTIME"], "description": "仅 capability 使用；APP_RUNTIME 返回权威 yamlSchema 双段模板和完整外部参数示例。"},
        ],
    },
    "get_system_asset_creation_examples": {
        "parameters": [
            {"name": "asset_type", "required": True, "allowed_values": ["seed_project", "capability"]},
            {"name": "limit", "required": False, "description": "最多返回多少个当前租户的真实参考资产，默认 3，最大 10。"},
        ],
        "returns": "当前租户远端 Git 资产的脱敏参考字段、权威创建 schema 和从零创建步骤。参考资产只可借鉴技术栈/命名/分支，不能复制其项目 ID、仓库地址或代码。",
    },
    "create_system_asset": {
        "parameters": [
            {"name": "asset_type", "required": True, "allowed_values": sorted(_ASSET_TYPES)},
            {"name": "payload", "required": True, "description": "先调用 get_system_asset_schema(asset_type)；能力为 APP_RUNTIME 时必须复制其 yamlSchema 双段模板，并为每个外部参数声明 scope。"},
            {"name": "confirmed", "required": False, "allowed_values": [False, True], "description": "先用 false 生成预览，取得用户确认后才可 true。"},
        ],
    },
    "update_system_asset": {
        "parameters": [
            {"name": "asset_type", "required": True, "allowed_values": sorted(_ASSET_TYPES)},
            {"name": "object_version_number", "required": True, "description": "正整数；从最近一次 get_system_asset 的结果读取。"},
            {"name": "payload", "required": True, "description": "先调用 get_system_asset_schema(asset_type)。"},
            {"name": "confirmed", "required": False, "allowed_values": [False, True]},
        ],
    },
    "change_system_asset_status": {
        "parameters": [
            {"name": "asset_type", "required": True, "allowed_values": ["seed_project", "capability", "environment", "knowledge_base", "mcp_server"], "description": "skill 不使用此工具。"},
            {"name": "status", "required": True, "allowed_values": ["enabled", "disabled"], "description": "本工具使用小写值。"},
            {"name": "object_version_number", "required": True, "description": "正整数；从最近一次读取结果获得。"},
            {"name": "confirmed", "required": False, "allowed_values": [False, True]},
        ],
    },
    "delete_system_asset": {
        "parameters": [
            {"name": "asset_type", "required": True, "allowed_values": sorted(_ASSET_TYPES)},
            {"name": "object_version_number", "required": True, "description": "正整数；从最近一次读取结果获得。"},
            {"name": "confirmed", "required": False, "allowed_values": [False, True]},
        ],
    },
    "list_system_deployment_environments": {
        "parameters": [{"name": "environment_tier", "required": False, "allowed_values": ["dev", "test", "staging", "prod", "custom"], "description": "过滤参数大小写不敏感；建议使用小写规范值。"}],
    },
    "list_environment_infrastructure_schemas": {
        "parameters": [],
        "returns": "基础设施 type/kind 和嵌套字段由控制面动态返回；创建或更新环境基础设施前必须先调用。",
    },
    "create_system_capability_git_repository": {
        "parameters": [
            {"name": "git_connection_id", "required": True, "description": "必须先调用 list_system_git_connections，从返回的 id 选择，不能猜测。"},
            {"name": "branch", "required": False, "description": "默认为当前分支；必须是有效 Git 分支名。"},
            {"name": "confirmed", "required": False, "allowed_values": [False, True]},
        ],
    },
    "create_system_asset_starter_repository": {
        "parameters": [
            {"name": "asset_type", "required": True, "allowed_values": ["seed_project", "capability"]},
            {"name": "repository_path", "required": True, "description": "用户明确提供的不存在或空的绝对目录。"},
            {"name": "git_connection_id", "required": True, "description": "必须先调用 list_system_git_connections，从返回的 id 选择。"},
            {"name": "code", "required": True, "description": "新资产的机器编码，同时默认用作新 Git 仓库名。"},
            {"name": "name", "required": True, "description": "新资产显示名称。"},
            {"name": "branch", "required": False, "description": "默认 main；必须是有效 Git 分支名。"},
            {"name": "confirmed", "required": False, "allowed_values": [False, True], "description": "先预览；确认后才会创建目录、首个提交、远端空仓和推送。"},
        ],
    },
    "configure_system_git_remote": {
        "parameters": [
            {"name": "remote_url", "required": True, "description": "只接受 HTTPS、SSH 或 Git SSH 地址。"},
            {"name": "replace_existing", "required": False, "allowed_values": [False, True], "description": "仅在明确替换 origin 时为 true。"},
            {"name": "confirmed", "required": False, "allowed_values": [False, True]},
        ],
    },
    "push_system_git_repository": {
        "parameters": [
            {"name": "branch", "required": False, "description": "默认为当前分支；必须是有效 Git 分支名。"},
            {"name": "git_connection_id", "required": False, "description": "如指定，必须来自 list_system_git_connections。"},
            {"name": "confirmed", "required": False, "allowed_values": [False, True]},
        ],
    },
}
_SENSITIVE_KEY_PARTS = ("token", "secret", "password", "credential", "authorization", "connection", "private_key")
_RAW_KUBECONFIG_KEYS = frozenset({
    "kubeconfig", "kube_config", "kubeconfigcontents", "kube_config_contents",
})
_SAFE_CONFIGURATION_STATUS_KEYS = frozenset({"tokenconfigured", "caconfigured"})
_registered_mcps: weakref.WeakSet[Any] = weakref.WeakSet()
_TRUSTED_CONTROL_PLANE_TENANT: ContextVar[str | None] = ContextVar(
    "_trusted_control_plane_tenant", default=None,
)


@contextmanager
def trusted_control_plane_tenant(tenant_id: str | None):
    """Bind the authenticated Control Plane tenant for one in-process tool call.

    It is deliberately a server-side context value rather than a tool argument:
    the model and external MCP callers must not choose the tenant header.
    """
    normalized = str(tenant_id or "").strip() or None
    token = _TRUSTED_CONTROL_PLANE_TENANT.set(normalized)
    try:
        yield
    finally:
        _TRUSTED_CONTROL_PLANE_TENANT.reset(token)


class AssetGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


class SystemGitError(RuntimeError):
    """A safe, actionable failure while operating an explicit local Git repo."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


_GIT_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_GIT_REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _system_git_root(repository_path: str) -> Path:
    """Resolve only an explicitly supplied local Git repository root.

    The system assistant never scans the filesystem for repositories.  A user
    must provide a concrete directory; this helper merely normalizes that one
    directory and asks Git for its actual worktree root.
    """
    supplied = str(repository_path or "").strip()
    if not supplied:
        raise SystemGitError("SYSTEM_GIT_PATH_REQUIRED", "repository_path 不能为空")
    candidate = Path(supplied).expanduser()
    if not candidate.is_absolute() or not candidate.is_dir():
        raise SystemGitError("SYSTEM_GIT_PATH_INVALID", "repository_path 必须是存在的绝对目录")
    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemGitError("SYSTEM_GIT_UNAVAILABLE", "无法执行本机 Git 命令") from exc
    root = result.stdout.strip()
    if result.returncode != 0 or not root:
        raise SystemGitError("SYSTEM_GIT_REPOSITORY_REQUIRED", "指定目录不是 Git 工作区")
    return Path(root).resolve()


def _run_git(root: Path, *args: str, check: bool = True) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], check=False,
            capture_output=True, text=True, timeout=45,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemGitError("SYSTEM_GIT_TIMEOUT", "Git 操作超时") from exc
    except OSError as exc:
        raise SystemGitError("SYSTEM_GIT_UNAVAILABLE", "无法执行本机 Git 命令") from exc
    if check and result.returncode != 0:
        detail = _safe_remote_url(
            (result.stderr or result.stdout or "Git 命令失败").strip().splitlines()[0][:300]
        )
        raise SystemGitError("SYSTEM_GIT_COMMAND_FAILED", detail)
    return (result.stdout or "").strip()


def _safe_remote_url(value: str) -> str:
    """Never echo a credential embedded in a Git remote URL."""
    text = str(value or "").strip()
    return re.sub(r"(https?://)[^/@\s]+@", r"\1***@", text)


def _read_capability_manifest(root: Path) -> dict[str, Any]:
    path = root / "capability.json"
    if not path.is_file():
        return {"present": False}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"present": True, "valid": False, "error": str(exc)[:200]}
    if not isinstance(raw, dict):
        return {"present": True, "valid": False, "error": "capability.json 根节点必须是对象"}

    # The current capability contract nests its identity under ``capability``;
    # retain support for the older flat form as well.
    identity = raw.get("capability") if isinstance(raw.get("capability"), dict) else raw

    dependencies: list[dict[str, Any]] = []
    for key in ("dependencies", "dependsOn", "capabilities"):
        value = raw.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    dependencies.append({"reference": item})
                elif isinstance(item, dict):
                    dependencies.append({
                        field: _safe(v) for field, v in item.items()
                        if field in {"name", "id", "code", "path", "repository", "version"}
                    })
    return {
        "present": True,
        "valid": True,
        "id": identity.get("id") or identity.get("code"),
        "name": identity.get("name") or identity.get("id") or identity.get("capabilityName") or identity.get("code"),
        "version": identity.get("version") or raw.get("version"),
        "dependencies": dependencies,
    }


def _capability_repository_name(root: Path, requested_name: str | None = None) -> str:
    """Pick a safe remote project name without guessing a namespace.

    Capability IDs are the preferred source because they stay stable if a local
    directory is renamed.  The caller may override the name, but it must remain
    a simple Git project slug (no slash, shell syntax, or traversal).
    """
    manifest = _read_capability_manifest(root)
    if not manifest.get("present") or not manifest.get("valid"):
        raise SystemGitError(
            "SYSTEM_CAPABILITY_MANIFEST_REQUIRED",
            "自动创建能力仓库需要仓库根目录存在有效的 capability.json",
        )
    raw_name = str(requested_name or manifest.get("id") or manifest.get("name") or root.name).strip()
    # ``_read_capability_manifest`` deliberately exposes a display name; get
    # the machine id here so Chinese display names never accidentally become a
    # provider-specific project slug.
    if not requested_name:
        try:
            raw = json.loads((root / "capability.json").read_text(encoding="utf-8"))
            identity = raw.get("capability") if isinstance(raw.get("capability"), dict) else raw
            raw_name = str(identity.get("id") or raw_name).strip()
        except (OSError, ValueError, AttributeError):
            pass
    if not _GIT_REPOSITORY_NAME_RE.fullmatch(raw_name):
        raise SystemGitError(
            "SYSTEM_GIT_REPOSITORY_NAME_INVALID",
            "repository_name 只能包含字母、数字、点、下划线和连字符，且不能包含斜杠",
        )
    return raw_name


def _clean_repository_remote(host: str, repo_full_path: str) -> str:
    base = str(host or "").rstrip("/")
    path = str(repo_full_path or "").strip("/")
    if not base.startswith("https://") or not path or any(part in {".", ".."} for part in path.split("/")):
        raise SystemGitError("SYSTEM_GIT_REMOTE_INVALID", "GitConnection 的 host 或仓库路径无效")
    return f"{base}/{path}.git"


def _new_system_git_root(repository_path: str) -> Path:
    """Validate one explicit empty directory as the target for a new repo."""
    supplied = str(repository_path or "").strip()
    if not supplied:
        raise SystemGitError("SYSTEM_GIT_PATH_REQUIRED", "repository_path 不能为空")
    candidate = Path(supplied).expanduser()
    if not candidate.is_absolute() or candidate == candidate.parent:
        raise SystemGitError("SYSTEM_GIT_PATH_INVALID", "repository_path 必须是明确的绝对目录，不能是根目录")
    if candidate.exists():
        if not candidate.is_dir():
            raise SystemGitError("SYSTEM_GIT_PATH_INVALID", "repository_path 必须是目录")
        if any(candidate.iterdir()):
            raise SystemGitError("SYSTEM_GIT_TARGET_NOT_EMPTY", "从零创建只接受不存在或空目录，避免覆盖已有文件")
    elif not candidate.parent.is_dir():
        raise SystemGitError("SYSTEM_GIT_PARENT_MISSING", "repository_path 的父目录必须已存在")
    return candidate.resolve()


def _starter_repository_name(code: str, requested_name: str | None = None) -> str:
    value = str(requested_name or code or "").strip()
    if not _GIT_REPOSITORY_NAME_RE.fullmatch(value):
        raise SystemGitError(
            "SYSTEM_GIT_REPOSITORY_NAME_INVALID",
            "code / repository_name 只能包含字母、数字、点、下划线和连字符，且不能包含斜杠",
        )
    return value


def _write_starter_repository_files(root: Path, asset_type: str, code: str, name: str, description: str | None) -> None:
    """Create the minimum auditable source skeleton before its first commit."""
    root.mkdir()
    summary = str(description or "").strip() or f"{name} 的系统资产工程。"
    (root / "README.md").write_text(f"# {name}\n\n{summary}\n", encoding="utf-8")
    (root / ".gitignore").write_text(".DS_Store\n.env\n", encoding="utf-8")
    if asset_type == "capability":
        (root / "capability.json").write_text(json.dumps({
            "capability": {"id": code, "name": name, "version": "0.1.0"},
            "description": summary,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        (root / "AGENTS.md").write_text(
            "# 工程约定\n\n"
            "在将此工程登记为种子工程前，请补齐实际技术栈、构建、测试和发布约定。\n",
            encoding="utf-8",
        )


def _system_git_snapshot(repository_path: str) -> dict[str, Any]:
    root = _system_git_root(repository_path)
    branch = _run_git(root, "branch", "--show-current")
    status = _run_git(root, "status", "--porcelain=v1")
    remotes = _run_git(root, "remote", check=False).splitlines()
    remote_urls = {
        name: _safe_remote_url(_run_git(root, "remote", "get-url", name, check=False))
        for name in remotes
    }
    head = _run_git(root, "log", "-1", "--pretty=format:%H%x00%s", check=False)
    commit, _, subject = head.partition("\x00")
    upstream = _run_git(root, "rev-parse", "--abbrev-ref", "@{upstream}", check=False)
    ahead = behind = None
    if upstream:
        counts = _run_git(root, "rev-list", "--left-right", "--count", f"{upstream}...HEAD", check=False)
        try:
            behind, ahead = (int(part) for part in counts.split()[:2])
        except (TypeError, ValueError):
            ahead = behind = None
    return {
        "repository_path": str(root),
        "branch": branch or None,
        "head_commit": commit or None,
        "head_subject": subject or None,
        "is_clean": not bool(status),
        "changed_files": len(status.splitlines()),
        "remotes": remote_urls,
        "has_origin": bool(remote_urls.get("origin")),
        "upstream": upstream or None,
        "ahead": ahead,
        "behind": behind,
        "capability": _read_capability_manifest(root),
    }


async def _system_git_connection(
    resolve_identity: Callable[[int | None, int | None], tuple[int, int]],
    tenant_id: int,
    user_id: int,
    git_connection_id: int | None,
) -> GitConnection | None:
    """Load a platform-configured Git credential without exposing its token."""
    if git_connection_id is None:
        return None
    resolved_tenant_id, _resolved_user_id = resolve_identity(tenant_id, user_id)
    try:
        connection_id = int(git_connection_id)
    except (TypeError, ValueError):
        raise SystemGitError("SYSTEM_GIT_CONNECTION_INVALID", "git_connection_id 必须是正整数")
    if connection_id < 1:
        raise SystemGitError("SYSTEM_GIT_CONNECTION_INVALID", "git_connection_id 必须是正整数")
    async with AsyncSessionLocal() as db:
        connection = await db.scalar(
            select(GitConnection)
            .join(Project, Project.id == GitConnection.project_id)
            .where(GitConnection.id == connection_id, Project.tenant_id == resolved_tenant_id)
        )
    if connection is None:
        raise SystemGitError("SYSTEM_GIT_CONNECTION_NOT_FOUND", "未找到当前租户可用的 GitConnection")
    if str(connection.status or "").lower() not in {"connected", "active", "enabled"}:
        raise SystemGitError("SYSTEM_GIT_CONNECTION_UNAVAILABLE", "所选 GitConnection 当前不可用")
    return connection


def _authenticated_git_remote(connection: GitConnection, remote_url: str) -> str:
    """Create a transient auth URL; callers must never persist or log it."""
    try:
        # GitConnection is written by app.git.connection.encrypt_token.  Use
        # its paired decryptor here; using the unrelated app password cipher
        # makes a valid platform connection look broken.
        from app.git.connection import decrypt_token
        token = decrypt_token(connection.access_token_enc)
    except Exception as exc:  # noqa: BLE001 - map stale encrypted credentials cleanly
        raise SystemGitError("SYSTEM_GIT_CONNECTION_CREDENTIAL_INVALID", "GitConnection 凭据无法解密，请重新配置") from exc
    try:
        from app.git.workspace_git import build_authed_url
        return build_authed_url(connection.provider, remote_url, token)
    finally:
        del token


@dataclass(frozen=True)
class AssetGateway:
    control_plane_base: str
    control_plane_token: str
    management_base: str
    management_token: str
    control_plane_tenant_id: str

    @classmethod
    async def for_user(cls, user_id: int) -> "AssetGateway":
        async with AsyncSessionLocal() as db:
            user = await db.scalar(select(User).where(User.id == int(user_id)))
        if user is None or not user.is_active:
            raise AssetGatewayError("SYSTEM_ASSET_IDENTITY_UNAVAILABLE", "当前用户不可用")
        control_token = control_plane_access_token(user) or ""
        management_token = remote_builder_access_token(user) or ""
        control_plane_tenant_id = (
            _TRUSTED_CONTROL_PLANE_TENANT.get()
            or str(getattr(user, "coding_tenant_id", "") or "").strip()
        )
        return cls(
            control_plane_base=control_plane_base_url().rstrip("/"),
            control_plane_token=control_token,
            management_base=_management_base_url(),
            management_token=management_token,
            control_plane_tenant_id=control_plane_tenant_id,
        )

    def request_headers(
        self,
        *,
        use_management: bool,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        token = self.management_token if use_management else self.control_plane_token
        headers = {"Authorization": f"Bearer {token}"}
        if self.control_plane_tenant_id:
            headers["X-Tenant-Id"] = self.control_plane_tenant_id
        if use_management:
            headers.update(_internal_headers())
        if extra_headers:
            headers.update(extra_headers)
        return headers

    async def request(
        self,
        *,
        asset_type: str,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        form: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        # Knowledge bases, Skills, and MCP servers are Builder AI Control Plane
        # assets.  They must never fall back to the desktop sidecar's local
        # knowledge/skill/MCP registries.
        use_management = asset_type in {"knowledge_base", "skill", "mcp_server"}
        base = self.management_base if use_management else self.control_plane_base
        token = self.management_token if use_management else self.control_plane_token
        if not base:
            raise AssetGatewayError("SYSTEM_ASSET_SERVICE_UNCONFIGURED", "系统资产管理服务未配置")
        if not token:
            raise AssetGatewayError("SYSTEM_ASSET_AUTH_REQUIRED", "请先登录可访问系统资产的控制面")
        headers = self.request_headers(
            use_management=use_management,
            extra_headers=extra_headers,
        )
        try:
            async with httpx.AsyncClient(base_url=base, timeout=30.0) as client:
                response = await client.request(
                    method, path, params=params,
                    json=None if files else body,
                    data=form if files else None,
                    files=files,
                    headers=headers,
                )
        except httpx.RequestError as exc:
            raise AssetGatewayError("SYSTEM_ASSET_SERVICE_UNAVAILABLE", "系统资产管理服务暂不可用") from exc
        if response.status_code >= 400:
            message = "系统资产操作失败"
            code = "SYSTEM_ASSET_REQUEST_FAILED"
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    message = str(payload.get("message") or payload.get("detail") or message)
                    code = str(payload.get("code") or payload.get("error_code") or code)
            except ValueError:
                pass
            raise AssetGatewayError(code, message, response.status_code)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise AssetGatewayError("SYSTEM_ASSET_INVALID_RESPONSE", "系统资产服务返回无效响应") from exc
        return payload if isinstance(payload, dict) else {"items": payload}


def _asset_path(asset_type: str, asset_id: str | None = None) -> str:
    root = {
        "seed_project": "/api/seed-projects",
        "capability": "/api/capabilities",
        "environment": "/api/environments",
        "knowledge_base": "/api/builder-ai/knowledge-bases",
        "skill": "/api/builder-ai/skills",
        "mcp_server": "/api/builder-ai/mcp-servers",
    }[asset_type]
    return root if not asset_id else f"{root}/{asset_id}"


def _require_asset_type(asset_type: str) -> str:
    value = str(asset_type or "").strip()
    if value not in _ASSET_TYPES:
        raise AssetGatewayError(
            "SYSTEM_ASSET_TYPE_INVALID",
            "asset_type 必须是 seed_project、capability、environment、knowledge_base、skill 或 mcp_server",
        )
    return value


def _asset_field_schema(asset_type: str) -> dict[str, Any]:
    """Return a detached schema so callers cannot mutate the process contract."""
    return json.loads(json.dumps(_ASSET_FIELD_SCHEMAS[asset_type]))


def _asset_result_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a bounded list from the compatible Control Plane envelopes."""
    candidates: list[Any] = [result.get("items"), result.get("records"), result.get("data")]
    data = result.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("items"), data.get("records"), data.get("content")])
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _creation_reference(asset_type: str, item: dict[str, Any]) -> dict[str, Any]:
    """Expose only safe, useful fields of a live reference asset."""
    fields = (
        ("id", "seedProjectId", "seedName", "name", "providerProjectId", "pathWithNamespace", "repositoryUrl", "branch", "description", "tagIds")
        if asset_type == "seed_project"
        else ("id", "capabilityId", "code", "name", "runtimeType", "agentCapabilityKind", "riskLevel", "status", "description", "tagIds")
    )
    return {
        field: _safe(item[field])
        for field in fields
        if item.get(field) not in (None, "", [], {})
    }


def _reference_repository(item: dict[str, Any]) -> tuple[str, str] | None:
    """Return the repository full path and branch from one asset response."""
    repo_path = str(item.get("pathWithNamespace") or item.get("repositoryFullPath") or "").strip().strip("/")
    branch = str(item.get("branch") or item.get("defaultBranch") or "main").strip()
    if not repo_path or not branch:
        return None
    return repo_path, branch


def _redact_reference_rule_text(value: str, *, limit: int = 6000) -> str:
    """Keep reference rules useful without reflecting accidental secrets."""
    text = str(value or "")[:limit]
    text = re.sub(
        r"(?im)^(\s*(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*).+$",
        r"\1***",
        text,
    )
    return text


async def _reference_rules_for_assets(
    resolve_identity: Callable[[int | None, int | None], tuple[int, int]],
    tenant_id: int,
    user_id: int,
    references: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """Read small, public engineering-rule files through a matching GitConnection."""
    resolved_tenant_id, _resolved_user_id = resolve_identity(tenant_id, user_id)
    try:
        async with AsyncSessionLocal() as db:
            connections = (await db.execute(
                select(GitConnection)
                .join(Project, Project.id == GitConnection.project_id)
                .where(Project.tenant_id == resolved_tenant_id)
                .order_by(GitConnection.id.asc())
            )).scalars().all()
    except Exception:
        return [], "参考工程规则来源暂不可用；已保留资产元数据和创建 schema。"
    active = [
        connection for connection in connections
        if str(connection.status or "").lower() in {"connected", "active", "enabled"}
    ]
    if not active:
        return [], "当前租户没有可用 GitConnection，未读取参考工程规则。"

    from app.git.connection import make_provider

    rules: list[dict[str, Any]] = []
    for item in references:
        coordinates = _reference_repository(item)
        if coordinates is None:
            continue
        repo_full_path, branch = coordinates
        # Asset repositories are governed by the tenant's Git connection.  A
        # configured connection is sufficient here; its token stays inside the
        # provider and is never returned to the model.
        connection = active[0]
        provider = make_provider(connection)
        files: list[dict[str, str]] = []
        for path in ("AGENTS.md", "README.md", "capability.json"):
            try:
                content = await provider.read_file(repo_full_path=repo_full_path, path=path, ref=branch)
            except Exception:  # missing optional file / unavailable provider
                continue
            if content.strip():
                files.append({"path": path, "content": _redact_reference_rule_text(content)})
        if files:
            rules.append({"repository": repo_full_path, "branch": branch, "files": files})
    if not rules:
        return [], "未读取到参考工程的 AGENTS.md、README.md 或 capability.json。"
    return rules, "已从当前租户的参考 Git 工程读取规则文件；请先向用户概括规则，再开始创建。"


def _from_scratch_steps(asset_type: str) -> list[str]:
    if asset_type == "seed_project":
        return [
            "先从 reference_assets 选择技术栈和目录约定相近的样例；只借鉴结构，不复制其 Git 项目 ID、仓库地址或代码。",
            "用户提供新建目录后，先选 list_system_git_connections 的连接，再用 create_system_asset_starter_repository 预览并确认；它会创建空仓、推送首个提交并返回 providerProjectId、pathWithNamespace、repositoryUrl 和 branch。",
            "调用 get_system_asset_schema(asset_type='seed_project')，按返回字段组装新 payload；先 create_system_asset(..., confirmed=false) 生成预览，得到用户确认后再 confirmed=true。",
        ]
    return [
        "先从 reference_assets 选择相近的运行时类型和风险等级；只借鉴设计，不复制 code、ID、Git 地址或外部参数值。",
        "先调用 get_system_asset_schema(asset_type='capability', runtime_type=...)；APP_RUNTIME 必须原样使用双段 yamlSchema 模板，AGENT_RUNTIME 需填写 agentCapabilityKind。",
        "用户提供新建目录后，先选 list_system_git_connections 的连接，再用 create_system_asset_starter_repository 预览并确认；它会生成 capability.json、创建空仓、绑定 origin 并推送首个提交。",
        "最后按 schema 调用 create_system_asset(..., confirmed=false) 预览；用户确认后才创建能力资产。",
    ]


def _capability_yaml_schema_contract() -> dict[str, Any]:
    """Return the complete, stable APP_RUNTIME configuration-schema contract."""
    return {
        "runtime_type": "APP_RUNTIME",
        "source": "Control Plane CapabilitySchemaPolicy",
        "recommended_root_keys": [
            "environmentInstanceRequired",
            "applicationEnvironmentInstanceRequired",
            "environmentInstanceSchema",
            "applicationEnvironmentInstanceSchema",
        ],
        "sections": {
            "environmentInstanceSchema": {
                "scope": "environment",
                "meaning": "同一环境内共享的外部参数，例如服务地址、区域、环境级凭据。实际值通过 environment.capabilityInstances[].yamlValues 配置。",
            },
            "applicationEnvironmentInstanceSchema": {
                "scope": "application_environment",
                "meaning": "某应用在某环境中的外部参数，例如项目标识、租户标识、应用级凭据。实际值通过 save_environment_capability_config 的 values 配置。",
            },
        },
        "section_shape": {
            "scope": "必须等于该段固定 scope",
            "required": "字符串数组；每个名字必须同时出现在 properties。",
            "properties": "对象；键是参数名，值是字段定义。",
        },
        "property_shape": {
            "type": "字符串（建议 string / number / boolean）。",
            "format": "可选；URL 用 uri。",
            "scope": "必须与所在段完全一致。",
            "sensitive": "布尔值；敏感参数必须为 true。",
            "title": "用户可读名称。",
            "ui.control": {"allowed_values": sorted(_CAPABILITY_SCHEMA_UI_CONTROLS)},
            "ui.options": "仅 ui.control=select 时必填；每项必须有非空 value 和 label。",
            "ui.writeOnly": "敏感参数必须为 true，且 ui.control 必须是 secretInput。",
            "agentHints.aliases": "可选字符串数组。",
        },
        "rules": [
            "新建 APP_RUNTIME 必须同时定义两段；不能写成 environment: 或 applicationEnvironment:。两个 *InstanceRequired 标志应始终显式写出。",
            "没有外部参数也必须使用下方完整空模板，不能使用 type: object / properties: {}。",
            "每个要由环境或应用提供的外部参数，必须在对应段的 properties 声明；required 只列必填参数。",
            "敏感值不写入 yamlSchema、描述或 metadata；schema 使用 sensitive: true + secretInput + writeOnly。",
            "运行时为 AGENT_RUNTIME 时不提供 yamlSchema；MCP 的连接配置使用 mcpConfig。",
        ],
        "templates": {
            "without_external_parameters": _CAPABILITY_APP_RUNTIME_SCHEMA_TEMPLATE,
            "with_external_parameters": _CAPABILITY_APP_RUNTIME_EXTERNAL_PARAMETERS_EXAMPLE,
        },
        "value_examples": {
            "environment_capability_instance_yamlValues": "serviceBaseUrl: https://api.example.internal\nserviceToken:\n  credentialRef: service-token-prod\n",
            "application_environment_instance_values": {"projectKey": "approval-center"},
            "sensitive_value_rule": "敏感值必须是 credentialRef、credential_ref、resolverRef 或 resolver_ref 的非空引用对象；不要传明文。",
        },
    }


def _capability_yaml_schema_issues(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Mirror the deterministic APP_RUNTIME schema rules before remote confirmation.

    This covers the Control Plane's creation contract (strict dual sections),
    so a model cannot receive a successful preview for a schema which will be
    rejected after the user confirms it.
    """
    if payload.get("runtimeType") != "APP_RUNTIME":
        if payload.get("runtimeType") == "AGENT_RUNTIME" and payload.get("yamlSchema") not in (None, ""):
            return [{"path": "yamlSchema", "message": "AGENT_RUNTIME 不使用 yamlSchema；MCP 使用 mcpConfig，SKILL 使用 skillArtifactUploadId。"}]
        return []

    raw_schema = payload.get("yamlSchema")
    if not isinstance(raw_schema, str) or not raw_schema.strip():
        return [{"path": "yamlSchema", "message": "APP_RUNTIME 必须提供非空 yamlSchema；先调用 get_system_asset_schema(asset_type='capability') 获取完整模板。"}]
    try:
        definition = yaml.safe_load(raw_schema)
    except yaml.YAMLError:
        return [{"path": "yamlSchema", "message": "yamlSchema 必须是有效 YAML。"}]
    if not isinstance(definition, dict):
        return [{"path": "yamlSchema", "message": "yamlSchema 根节点必须是 YAML 对象。"}]

    issues: list[dict[str, Any]] = []
    for key in ("environmentInstanceSchema", "applicationEnvironmentInstanceSchema"):
        if key not in definition:
            issues.append({"path": key, "message": "新建 APP_RUNTIME 必须同时包含 environmentInstanceSchema 和 applicationEnvironmentInstanceSchema；不能使用 environment: 代替。"})
    if issues:
        return issues

    expected_scopes = {
        "environmentInstanceSchema": "environment",
        "applicationEnvironmentInstanceSchema": "application_environment",
    }
    for section_name, expected_scope in expected_scopes.items():
        section = definition.get(section_name)
        if not isinstance(section, dict):
            issues.append({"path": section_name, "message": "段必须是对象。"})
            continue
        if section.get("scope") != expected_scope:
            issues.append({"path": f"{section_name}.scope", "message": f"必须为 {expected_scope!r}。"})
        required = section.get("required", [])
        properties = section.get("properties", {})
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            issues.append({"path": f"{section_name}.required", "message": "必须是字符串数组。"})
            required = []
        if not isinstance(properties, dict):
            issues.append({"path": f"{section_name}.properties", "message": "必须是对象。"})
            continue
        for name in required:
            if name not in properties:
                issues.append({"path": f"{section_name}.required", "message": f"必填字段 {name!r} 未在 properties 声明。"})
        for field_name, field in properties.items():
            path = f"{section_name}.properties.{field_name}"
            if not isinstance(field, dict):
                issues.append({"path": path, "message": "字段定义必须是对象。"})
                continue
            if field.get("scope") != expected_scope:
                issues.append({"path": f"{path}.scope", "message": f"必须与所属段一致：{expected_scope!r}。"})
            ui = field.get("ui") if isinstance(field.get("ui"), dict) else {}
            control = ui.get("control")
            if control is not None and control not in _CAPABILITY_SCHEMA_UI_CONTROLS:
                issues.append({"path": f"{path}.ui.control", "message": f"不支持的控件；可选值：{', '.join(sorted(_CAPABILITY_SCHEMA_UI_CONTROLS))}。"})
            if control == "select":
                options = ui.get("options")
                valid_options = isinstance(options, list) and bool(options) and all(
                    isinstance(option, dict)
                    and isinstance(option.get("value"), str) and bool(option["value"].strip())
                    and isinstance(option.get("label"), str) and bool(option["label"].strip())
                    for option in options
                )
                if not valid_options:
                    issues.append({"path": f"{path}.ui.options", "message": "select 必须提供非空 options，每项包含非空 value 和 label。"})
            if field.get("sensitive") is True and (control != "secretInput" or ui.get("writeOnly") is not True):
                issues.append({"path": f"{path}.ui", "message": "敏感字段必须使用 ui.control=secretInput 且 ui.writeOnly=true。"})
            agent_hints = field.get("agentHints")
            if isinstance(agent_hints, dict) and "aliases" in agent_hints:
                aliases = agent_hints["aliases"]
                if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
                    issues.append({"path": f"{path}.agentHints.aliases", "message": "必须是字符串数组。"})
    return issues


def _payload_contract_issues(asset_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Find deterministic payload errors before a confirmation or remote write.

    We intentionally validate only values and field names backed by a published
    Control Plane contract.  Required-field validation remains server-side so a
    caller can construct a draft incrementally, but a made-up enum must never
    reach the confirmation step as though it were valid.
    """
    schema = _ASSET_FIELD_SCHEMAS.get(asset_type, {})
    declared = {
        field["name"] for field in schema.get("create_fields", [])
        if isinstance(field, dict) and isinstance(field.get("name"), str)
    }
    enums = _LOCAL_ENUM_FIELDS.get(asset_type, {})
    invalid_fields = []
    for field, allowed_values in enums.items():
        if field not in payload or payload[field] is None:
            continue
        value = payload[field]
        if not isinstance(value, str) or value not in allowed_values:
            invalid_fields.append({
                "field": field,
                "provided": value,
                "allowed_values": sorted(allowed_values),
            })

    unsupported_fields = sorted(
        field for field in payload
        if declared and field not in declared
    )
    conditional_errors = []
    if asset_type == "capability":
        runtime_type = payload.get("runtimeType")
        agent_kind = payload.get("agentCapabilityKind")
        if runtime_type == "AGENT_RUNTIME" and not agent_kind:
            conditional_errors.append({
                "field": "agentCapabilityKind",
                "message": "runtimeType=AGENT_RUNTIME 时必须填写。",
                "allowed_values": ["MCP", "SKILL"],
            })
        if runtime_type == "APP_RUNTIME" and agent_kind:
            conditional_errors.append({
                "field": "agentCapabilityKind",
                "message": "runtimeType=APP_RUNTIME 时不能填写该字段。",
            })
        conditional_errors.extend(_capability_yaml_schema_issues(payload))
    return {
        "invalid_fields": invalid_fields,
        "unsupported_fields": unsupported_fields,
        "conditional_errors": conditional_errors,
    }


def _payload_contract_error(asset_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    issues = _payload_contract_issues(asset_type, payload)
    if not any(issues.values()):
        return None
    if issues["invalid_fields"]:
        code = "SYSTEM_ASSET_FIELD_VALUE_INVALID"
        message = "系统资产字段值无效；请使用 schema 返回的 allowed_values 原样填写，不能猜测展示文案或大小写。"
    elif issues["unsupported_fields"]:
        code = "SYSTEM_ASSET_FIELD_UNSUPPORTED"
        message = "payload 包含当前资产接口不支持的字段；请使用 schema 中列出的字段。"
    elif any(str(issue.get("path") or "").startswith(("yamlSchema", "environmentInstanceSchema", "applicationEnvironmentInstanceSchema")) for issue in issues["conditional_errors"]):
        code = "CAPABILITY_YAML_SCHEMA_INVALID"
        message = "APP_RUNTIME 的 yamlSchema 不符合 Control Plane 双段契约；请使用 get_system_asset_schema 返回的完整模板，不要猜测 environment 段。"
    else:
        code = "SYSTEM_ASSET_FIELD_CONDITION_INVALID"
        message = "payload 不满足字段依赖规则；请按 schema 的 required_when / forbidden_when 调整。"
    return _err(
        code,
        message,
        asset_type=asset_type,
        **issues,
        schema=_asset_field_schema(asset_type),
        capability_yaml_schema=_capability_yaml_schema_contract() if asset_type == "capability" else None,
    )


def _safe(value: Any, *, key: str = "") -> Any:
    normalized = key.lower().replace("-", "_")
    compact = normalized.replace("_", "")
    # Control Plane normally returns a kubeConfigSummary instead of the raw
    # kubeConfig.  Keep this second barrier in the desktop backend as well:
    # an upstream regression must not turn a System Assistant query into a
    # credential disclosure.  The summary's boolean status fields are safe.
    if normalized in _RAW_KUBECONFIG_KEYS or compact in _RAW_KUBECONFIG_KEYS:
        return "<redacted>"
    if compact in _SAFE_CONFIGURATION_STATUS_KEYS and isinstance(value, bool):
        return value
    if normalized == "values" or any(part in normalized for part in _SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _safe(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value


def _confirmation_preview(action: str, asset_type: str, asset_id: str | None, payload: dict[str, Any] | None) -> dict[str, Any]:
    return _ok(
        confirmation_required=True,
        action=action,
        asset_type=asset_type,
        asset_id=asset_id,
        preview=_safe(payload or {}),
        message="请向用户展示以上变更并取得明确确认后，再以 confirmed=true 执行。",
    )


async def _gateway(resolve_identity: Callable[[int | None, int | None], tuple[int, int]], tenant_id: int, user_id: int) -> AssetGateway:
    _tenant_id, resolved_user_id = resolve_identity(tenant_id, user_id)
    return await AssetGateway.for_user(resolved_user_id)


def register(mcp, resolve_identity: Callable[[int | None, int | None], tuple[int, int]]):
    """Register the system-only asset-management tools on the shared FastMCP."""
    if mcp in _registered_mcps:
        return
    _registered_mcps.add(mcp)

    @mcp.tool()
    async def list_system_assets(asset_type: str, keyword: str | None = None, page: int = 1, page_size: int = 50, tenant_id: int = 0, user_id: int = 0) -> dict:
        """列出远端系统资产。asset_type: seed_project、capability、environment、knowledge_base、skill 或 mcp_server。"""
        try:
            kind = _require_asset_type(asset_type)
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            params: dict[str, Any] = {}
            if kind in {"seed_project", "capability", "knowledge_base", "skill", "mcp_server"} and keyword:
                params["keyword"] = keyword
            if kind in {"capability", "knowledge_base", "skill", "mcp_server"}:
                params.update({"page": max(1, int(page)), "pageSize": min(100, max(1, int(page_size)))})
            result = await gateway.request(asset_type=kind, method="GET", path=_asset_path(kind), params=params)
            return _ok(asset_type=kind, result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def get_system_asset(asset_type: str, asset_id: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """读取一项系统资产详情；响应会自动删除密钥、连接信息和敏感配置值。"""
        try:
            kind = _require_asset_type(asset_type)
            if not str(asset_id).strip():
                return _err("SYSTEM_ASSET_ID_REQUIRED", "asset_id 不能为空")
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(asset_type=kind, method="GET", path=_asset_path(kind, asset_id))
            return _ok(asset_type=kind, result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def get_system_asset_schema(asset_type: str, runtime_type: str | None = None) -> dict:
        """读取系统资产的创建/更新字段契约、必填规则、枚举值和完整示例。

        创建或更新前必须先调用本工具；allowed_values 中的值必须原样使用，不能根据
        中文展示名、旧接口或经验猜测。对于 APP_RUNTIME capability，返回的
        capability_yaml_schema 是 Control Plane 的严格双段契约：每一个需要由外部
        环境或应用提供的参数，都必须在其中声明，再单独配置实际值。
        """
        try:
            kind = _require_asset_type(asset_type)
            normalized_runtime_type = str(runtime_type or "").strip()
            if normalized_runtime_type and normalized_runtime_type not in _LOCAL_ENUM_FIELDS["capability"]["runtimeType"]:
                return _err(
                    "CAPABILITY_RUNTIME_TYPE_INVALID",
                    "runtime_type 必须是 AGENT_RUNTIME 或 APP_RUNTIME。",
                    allowed_values=sorted(_LOCAL_ENUM_FIELDS["capability"]["runtimeType"]),
                )
            result: dict[str, Any] = {
                "asset_type": kind,
                "schema": _asset_field_schema(kind),
                "message": "创建或更新前请严格使用 schema 中的字段和 allowed_values；不确定时不要猜测。",
            }
            if kind == "capability":
                result["capability_yaml_schema"] = _capability_yaml_schema_contract()
                result["runtime_type"] = normalized_runtime_type or None
            return _ok(**result)
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def get_system_asset_creation_examples(
        asset_type: str,
        limit: int = 3,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """读取当前租户真实 Git 资产，作为种子工程或能力从零创建的参考。

        只返回适合借鉴的脱敏元数据和权威 schema；已有项目 ID、仓库地址、
        能力 code 与外部参数都不能复制到新资产。
        """
        try:
            kind = str(asset_type or "").strip()
            if kind not in {"seed_project", "capability"}:
                return _err(
                    "SYSTEM_ASSET_CREATION_EXAMPLE_TYPE_INVALID",
                    "asset_type 只能是 seed_project 或 capability",
                )
            page_size = min(10, max(1, int(limit)))
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            params: dict[str, Any] = {"page": 1, "pageSize": page_size} if kind == "capability" else {}
            result = await gateway.request(
                asset_type=kind,
                method="GET",
                path=_asset_path(kind),
                params=params,
            )
            items = _asset_result_items(result)
            reference_items = items[:page_size]
            reference_rules, rules_status = await _reference_rules_for_assets(
                resolve_identity, tenant_id, user_id, reference_items,
            )
            return _ok(
                asset_type=kind,
                reference_asset_count=len(items),
                reference_assets=[_creation_reference(kind, item) for item in reference_items],
                reference_rules=reference_rules,
                reference_rules_status=rules_status,
                schema=_asset_field_schema(kind),
                from_scratch_steps=_from_scratch_steps(kind),
                copy_safety="参考资产仅用于选择技术栈和约定；不得复制其仓库、项目 ID、机器编码或外部参数值，新资产必须使用新的 Git 仓库与标识。",
            )
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def get_system_assistant_mcp_contract(tool_name: str | None = None) -> dict:
        """读取系统助手 MCP 的固定参数值、格式约束和上游选择来源。

        传具体 tool_name 只读取该工具；留空返回全部已审计的固定值契约。动态环境
        基础设施字段仍以 list_environment_infrastructure_schemas 的实时结果为准。
        """
        requested = str(tool_name or "").strip()
        if requested:
            contract = _SYSTEM_ASSISTANT_MCP_CONTRACTS.get(requested)
            if contract is None:
                return _err(
                    "SYSTEM_ASSISTANT_MCP_CONTRACT_UNAVAILABLE",
                    "该系统助手 MCP 没有固定值契约；请直接阅读其工具 schema，不能猜测参数。",
                    tool_name=requested,
                    available_tool_names=sorted(_SYSTEM_ASSISTANT_MCP_CONTRACTS),
                )
            return _ok(tool_name=requested, contract=_safe(contract))
        return _ok(
            contracts={name: _safe(contract) for name, contract in _SYSTEM_ASSISTANT_MCP_CONTRACTS.items()},
            message="只列出真实的固定值、格式约束和依赖来源；未列字段是自由文本、ID 或由上游 Schema 动态决定。",
        )

    @mcp.tool()
    async def create_system_asset(asset_type: str, payload: dict, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """创建远端种子工程、能力、环境、知识库或 MCP 服务。首次调用只生成确认预览。"""
        try:
            kind = _require_asset_type(asset_type)
            if kind == "skill":
                return _err("SYSTEM_ASSET_USE_CREATE_SKILL", "Skill 请使用 create_system_skill，以便同时提供版本和内容")
            if not isinstance(payload, dict):
                return _err("SYSTEM_ASSET_PAYLOAD_INVALID", "payload 必须是对象")
            contract_error = _payload_contract_error(kind, payload)
            if contract_error:
                return contract_error
            if not confirmed:
                return _confirmation_preview("create", kind, None, payload)
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(asset_type=kind, method="POST", path=_asset_path(kind), body=payload)
            return _ok(asset_type=kind, result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def update_system_asset(asset_type: str, asset_id: str, payload: dict, object_version_number: int, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """修改系统资产。object_version_number 必须来自最近一次读取，防止覆盖其他人的修改。"""
        try:
            kind = _require_asset_type(asset_type)
            if not isinstance(payload, dict) or int(object_version_number or 0) < 1:
                return _err("SYSTEM_ASSET_VERSION_REQUIRED", "payload 和正整数 object_version_number 是必填项")
            contract_error = _payload_contract_error(kind, payload)
            if contract_error:
                return contract_error
            prepared = {**payload, "object_version_number": int(object_version_number)}
            if not confirmed:
                return _confirmation_preview("update", kind, asset_id, prepared)
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            headers = {"If-Match": str(object_version_number)} if kind in {"knowledge_base", "skill", "mcp_server"} else None
            # Builder-AI's patch DTO only accepts the editable fields; its
            # optimistic version belongs exclusively in If-Match.
            body = payload if kind in {"knowledge_base", "skill", "mcp_server"} else prepared
            result = await gateway.request(asset_type=kind, method="PATCH", path=_asset_path(kind, asset_id), body=body, extra_headers=headers)
            return _ok(asset_type=kind, result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def change_system_asset_status(asset_type: str, asset_id: str, status: str, object_version_number: int, reason: str | None = None, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """启用或禁用远端种子工程、能力、环境、知识库或 MCP 服务。禁用环境时必须提供 reason。"""
        try:
            kind = _require_asset_type(asset_type)
            desired = str(status or "").lower()
            if kind == "skill" or desired not in {"enabled", "disabled"}:
                return _err("SYSTEM_ASSET_STATUS_INVALID", "仅种子工程、能力、环境、知识库、MCP 服务支持 enabled / disabled")
            payload = {"status": desired, "object_version_number": int(object_version_number or 0), "reason": reason}
            if payload["object_version_number"] < 1:
                return _err("SYSTEM_ASSET_VERSION_REQUIRED", "object_version_number 必须是正整数")
            if not confirmed:
                return _confirmation_preview("change_status", kind, asset_id, payload)
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            if kind in {"knowledge_base", "mcp_server"}:
                path = f"{_asset_path(kind, asset_id)}/{'enable' if desired == 'enabled' else 'disable'}"
                result = await gateway.request(asset_type=kind, method="POST", path=path, extra_headers={"If-Match": str(object_version_number)})
            elif kind in {"capability", "environment"}:
                # Capabilities and environments use explicit enable/disable
                # endpoints, rather than a generic /status route.
                path = f"{_asset_path(kind, asset_id)}/{'enable' if desired == 'enabled' else 'disable'}"
                result = await gateway.request(asset_type=kind, method="POST", path=path, body=payload)
            else:
                result = await gateway.request(asset_type=kind, method="PATCH", path=f"{_asset_path(kind, asset_id)}/status", body=payload)
            return _ok(asset_type=kind, result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def delete_system_asset(asset_type: str, asset_id: str, object_version_number: int, reason: str | None = None, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """删除系统资产。先查 deletion-check（环境/能力）并向用户确认，删除不可撤销。"""
        try:
            kind = _require_asset_type(asset_type)
            version = int(object_version_number or 0)
            if version < 1:
                return _err("SYSTEM_ASSET_VERSION_REQUIRED", "object_version_number 必须是正整数")
            payload = {"object_version_number": version, "reason": reason}
            if not confirmed:
                return _confirmation_preview("delete", kind, asset_id, payload)
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            if kind in {"capability", "environment"}:
                check = await gateway.request(asset_type=kind, method="GET", path=f"{_asset_path(kind, asset_id)}/deletion-check")
                if not check.get("deletable", False):
                    return _err("SYSTEM_ASSET_DELETE_BLOCKED", "该资产仍被引用，不能删除", deletion_check=_safe(check))
            if kind in {"knowledge_base", "skill", "mcp_server"}:
                result = await gateway.request(asset_type=kind, method="DELETE", path=_asset_path(kind, asset_id), extra_headers={"If-Match": str(version)})
            else:
                result = await gateway.request(asset_type=kind, method="DELETE", path=_asset_path(kind, asset_id), body=payload)
            return _ok(asset_type=kind, result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def get_environment_capability_config(application_id: str, environment_id: str, capability_code: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """读取应用在环境中的能力配置和 readiness；不返回配置值或 Secret。"""
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            path = f"/api/applications/{application_id}/environments/{environment_id}/capabilities/{capability_code}/instance-config"
            config = await gateway.request(asset_type="environment", method="GET", path=path)
            readiness = await gateway.request(
                asset_type="environment", method="GET",
                path=path.removesuffix("/instance-config") + "/readiness",
            )
            return _ok(config=_safe(config), readiness=_safe(readiness))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def save_environment_capability_config(application_id: str, environment_id: str, capability_code: str, values: dict, object_version_number: int | None = None, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """保存应用-环境能力配置；values 只提交给控制面，响应不会回显敏感内容。"""
        try:
            if not isinstance(values, dict):
                return _err("SYSTEM_ASSET_PAYLOAD_INVALID", "values 必须是对象")
            payload = {"values": values, "object_version_number": object_version_number}
            if not confirmed:
                return _confirmation_preview("save_environment_capability_config", "environment", environment_id, payload)
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            path = f"/api/applications/{application_id}/environments/{environment_id}/capabilities/{capability_code}/instance-config"
            result = await gateway.request(asset_type="environment", method="PUT", path=path, body=payload)
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def delete_environment_capability_config(application_id: str, environment_id: str, capability_code: str, object_version_number: int | None = None, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """删除应用在某环境的能力配置绑定。首次调用只生成确认预览。"""
        try:
            payload = {"object_version_number": object_version_number}
            if not confirmed:
                return _confirmation_preview("delete_environment_capability_config", "environment", environment_id, payload)
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            path = f"/api/applications/{application_id}/environments/{environment_id}/capabilities/{capability_code}/instance-config"
            result = await gateway.request(asset_type="environment", method="DELETE", path=path, body=payload)
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def list_system_deployment_environments(
        environment_tier: str | None = None,
        include_infrastructure: bool = True,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """列出当前可用部署环境及其部署基础设施摘要。

        ``environment_tier`` 可传 test、staging、prod 等精确层级。开启
        ``include_infrastructure`` 时会读取每个环境详情，返回 K8S 的 namespace、
        ingress 和 kubeConfigSummary；原始 kubeconfig、token 与其他敏感字段始终不返回。
        """
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            listing = await gateway.request(
                asset_type="environment", method="GET", path=_asset_path("environment"),
            )
            raw_items = listing.get("items") if isinstance(listing, dict) else []
            if not isinstance(raw_items, list):
                raw_items = []
            desired_tier = str(environment_tier or "").strip().lower()
            items: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                if desired_tier and str(item.get("environmentTier") or "").strip().lower() != desired_tier:
                    continue
                environment_id = str(item.get("environmentId") or "").strip()
                detail = item
                if include_infrastructure and environment_id:
                    detail = await gateway.request(
                        asset_type="environment", method="GET",
                        path=_asset_path("environment", environment_id),
                    )
                infrastructure = detail.get("infrastructureInstances") if isinstance(detail, dict) else []
                deployment_instances = [
                    instance for instance in infrastructure if isinstance(instance, dict)
                    and str(instance.get("infrastructureType") or "").upper() == "DEPLOYMENT"
                ] if isinstance(infrastructure, list) else []
                items.append(_safe({
                    "environmentId": detail.get("environmentId") if isinstance(detail, dict) else environment_id,
                    "environmentName": detail.get("environmentName") if isinstance(detail, dict) else item.get("environmentName"),
                    "environmentTier": detail.get("environmentTier") if isinstance(detail, dict) else item.get("environmentTier"),
                    "environmentRiskLevel": detail.get("environmentRiskLevel") if isinstance(detail, dict) else item.get("environmentRiskLevel"),
                    "status": detail.get("status") if isinstance(detail, dict) else item.get("status"),
                    "object_version_number": detail.get("object_version_number") if isinstance(detail, dict) else item.get("object_version_number"),
                    "infrastructureSummary": detail.get("infrastructureSummary") if isinstance(detail, dict) else item.get("infrastructureSummary"),
                    "deploymentInfrastructure": deployment_instances,
                }))
            return _ok(environments=items, count=len(items))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def list_environment_infrastructure_schemas(tenant_id: int = 0, user_id: int = 0) -> dict:
        """读取环境基础设施配置表单 Schema（含 K8S 必填项与敏感字段标记，不含配置值）。"""
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="environment", method="GET",
                path="/api/environments/infrastructure-form-schemas",
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def upload_knowledge_document(knowledge_base_id: str, filename: str, content: str, title: str | None = None, tags: list[str] | None = None, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """上传一份文本知识文档到知识库。内容不会在工具结果中回显。"""
        payload = {"filename": filename, "title": title, "tags": tags or [], "content_length": len(content or "")}
        if not confirmed:
            return _confirmation_preview("upload_knowledge_document", "knowledge_base", knowledge_base_id, payload)
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="knowledge_base", method="POST", path=f"{_asset_path('knowledge_base', knowledge_base_id)}/documents",
                files={"file": (filename or "document.md", (content or "").encode("utf-8"), "text/markdown")},
                form={"title": title or "", "tags": tags or []},
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def list_knowledge_documents(knowledge_base_id: str, page: int = 1, page_size: int = 50, tenant_id: int = 0, user_id: int = 0) -> dict:
        """列出知识库文档及索引状态，正文不会回显。"""
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="knowledge_base", method="GET",
                path=f"{_asset_path('knowledge_base', knowledge_base_id)}/documents",
                params={"page": max(1, int(page)), "pageSize": min(100, max(1, int(page_size)))},
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def get_knowledge_document(knowledge_base_id: str, document_id: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """读取知识文档元数据和索引状态，不返回正文内容。"""
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="knowledge_base", method="GET",
                path=f"{_asset_path('knowledge_base', knowledge_base_id)}/documents/{document_id}",
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def delete_knowledge_document(knowledge_base_id: str, document_id: str, object_version_number: int, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """删除知识库文档。首次调用只产生确认预览。"""
        version = int(object_version_number or 0)
        if version < 1:
            return _err("SYSTEM_ASSET_VERSION_REQUIRED", "object_version_number 必须是正整数")
        if not confirmed:
            return _confirmation_preview("delete_knowledge_document", "knowledge_base", knowledge_base_id, {"document_id": document_id, "object_version_number": version})
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="knowledge_base", method="DELETE",
                path=f"{_asset_path('knowledge_base', knowledge_base_id)}/documents/{document_id}",
                extra_headers={"If-Match": str(version)},
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def publish_knowledge_document(knowledge_base_id: str, document_id: str, object_version_number: int, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """发布知识文档到检索索引。发布是异步任务，首次调用只生成确认预览。"""
        payload = {"object_version_number": int(object_version_number or 0)}
        if payload["object_version_number"] < 1:
            return _err("SYSTEM_ASSET_VERSION_REQUIRED", "object_version_number 必须是正整数")
        if not confirmed:
            return _confirmation_preview("publish_knowledge_document", "knowledge_base", knowledge_base_id, payload)
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="knowledge_base", method="POST",
                path=f"{_asset_path('knowledge_base', knowledge_base_id)}/documents/{document_id}/publish",
                extra_headers={"If-Match": str(object_version_number), "Idempotency-Key": f"system-assistant-{knowledge_base_id}-{document_id}-{object_version_number}"},
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def disable_knowledge_document(knowledge_base_id: str, document_id: str, object_version_number: int, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """下线知识文档，使其不再参与检索。"""
        version = int(object_version_number or 0)
        if version < 1:
            return _err("SYSTEM_ASSET_VERSION_REQUIRED", "object_version_number 必须是正整数")
        if not confirmed:
            return _confirmation_preview("disable_knowledge_document", "knowledge_base", knowledge_base_id, {"document_id": document_id, "object_version_number": version})
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="knowledge_base", method="POST",
                path=f"{_asset_path('knowledge_base', knowledge_base_id)}/documents/{document_id}/disable",
                extra_headers={"If-Match": str(version)},
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def reindex_knowledge_document(knowledge_base_id: str, document_id: str, object_version_number: int, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """重新索引知识文档。首次调用只产生确认预览。"""
        version = int(object_version_number or 0)
        if version < 1:
            return _err("SYSTEM_ASSET_VERSION_REQUIRED", "object_version_number 必须是正整数")
        if not confirmed:
            return _confirmation_preview("reindex_knowledge_document", "knowledge_base", knowledge_base_id, {"document_id": document_id, "object_version_number": version})
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="knowledge_base", method="POST",
                path=f"{_asset_path('knowledge_base', knowledge_base_id)}/documents/{document_id}/reindex",
                extra_headers={"If-Match": str(version), "Idempotency-Key": f"system-assistant-reindex-{knowledge_base_id}-{document_id}-{version}"},
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def create_system_skill(name: str, version: str, instructions: str, description: str | None = None, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """创建远程系统 Skill，并把 instructions 包装为标准 SKILL.md zip。"""
        payload = {"name": name, "version": version, "description": description, "instructions_length": len(instructions or "")}
        if not confirmed:
            return _confirmation_preview("create_system_skill", "skill", None, payload)
        try:
            frontmatter = f"---\nname: {name}\ndescription: {description or ''}\n---\n{instructions}\n"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("SKILL.md", frontmatter)
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="skill", method="POST", path=_asset_path("skill"),
                files={"artifact": ("skill.zip", buffer.getvalue(), "application/zip")},
                form={"name": name, "description": description or "", "version": version},
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def list_system_skill_versions(skill_id: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """列出远程系统 Skill 的所有版本、校验结果和启用状态。"""
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(asset_type="skill", method="GET", path=f"{_asset_path('skill', skill_id)}/versions")
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def create_system_skill_version(skill_id: str, version: str, instructions: str, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """为远程系统 Skill 上传一个新的 SKILL.md 版本。"""
        payload = {"version": version, "instructions_length": len(instructions or "")}
        if not confirmed:
            return _confirmation_preview("create_system_skill_version", "skill", skill_id, payload)
        try:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("SKILL.md", instructions or "")
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="skill", method="POST", path=f"{_asset_path('skill', skill_id)}/versions",
                files={"artifact": ("skill.zip", buffer.getvalue(), "application/zip")},
                form={"version": version},
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def enable_system_skill_version(skill_id: str, version_id: str, object_version_number: int, confirmed: bool = False, tenant_id: int = 0, user_id: int = 0) -> dict:
        """启用指定的远程系统 Skill 版本。"""
        payload = {"object_version_number": int(object_version_number or 0)}
        if payload["object_version_number"] < 1:
            return _err("SYSTEM_ASSET_VERSION_REQUIRED", "object_version_number 必须是正整数")
        if not confirmed:
            return _confirmation_preview("enable_system_skill_version", "skill", skill_id, payload)
        try:
            gateway = await _gateway(resolve_identity, tenant_id, user_id)
            result = await gateway.request(
                asset_type="skill", method="POST", path=f"{_asset_path('skill', skill_id)}/versions/{version_id}/enable",
                extra_headers={"If-Match": str(object_version_number)},
            )
            return _ok(result=_safe(result))
        except AssetGatewayError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def inspect_system_git_repository(repository_path: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """检查用户明确指定的本地系统资产 Git 仓库。

        返回当前分支、提交、未提交改动、origin/upstream、ahead/behind 与 capability.json
        摘要。不会扫描其他目录、不会修改仓库、不会读取或回显 Git 凭据。
        """
        try:
            resolve_identity(tenant_id, user_id)
            return _ok(result=_system_git_snapshot(repository_path))
        except SystemGitError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def list_system_git_connections(tenant_id: int = 0, user_id: int = 0) -> dict:
        """列出当前租户已配置且可供系统资产仓库推送使用的 GitConnection。

        只返回连接 ID、provider、host、项目和状态，绝不返回访问令牌。
        """
        try:
            resolved_tenant_id, _resolved_user_id = resolve_identity(tenant_id, user_id)
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(
                    select(GitConnection, Project)
                    .join(Project, Project.id == GitConnection.project_id)
                    .where(Project.tenant_id == resolved_tenant_id)
                    .order_by(Project.id.asc(), GitConnection.id.asc())
                )).all()
            return _ok(connections=[{
                "id": connection.id,
                "provider": connection.provider,
                "host": connection.host,
                "project_id": connection.project_id,
                "project_name": project.name,
                "group_id_or_org": connection.group_id_or_org,
                "status": connection.status,
            } for connection, project in rows])
        except SystemGitError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def create_system_asset_starter_repository(
        asset_type: str,
        repository_path: str,
        git_connection_id: int,
        code: str,
        name: str,
        description: str | None = None,
        repository_name: str | None = None,
        branch: str = "main",
        confirmed: bool = False,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """从零初始化种子工程或能力的 Git 工程，并在平台 Git 组建空仓后推送。

        只接受用户明确提供的空目录。首次调用只展示将写入的文件和将创建的
        Git 仓库；确认后才进行本地写入、首个提交、远端建仓及 push。
        """
        try:
            kind = str(asset_type or "").strip()
            if kind not in {"seed_project", "capability"}:
                return _err("SYSTEM_ASSET_STARTER_TYPE_INVALID", "asset_type 只能是 seed_project 或 capability")
            normalized_code = str(code or "").strip()
            project_name = _starter_repository_name(normalized_code, repository_name)
            display_name = str(name or "").strip()
            if not display_name:
                return _err("SYSTEM_ASSET_STARTER_NAME_REQUIRED", "name 不能为空")
            target_branch = str(branch or "").strip()
            if not target_branch or not _GIT_BRANCH_RE.fullmatch(target_branch) or target_branch.startswith("-"):
                return _err("SYSTEM_GIT_BRANCH_INVALID", "branch 必须是有效的非空 Git 分支名")
            root = _new_system_git_root(repository_path)
            connection = await _system_git_connection(resolve_identity, tenant_id, user_id, git_connection_id)
            if connection is None:
                return _err("SYSTEM_GIT_CONNECTION_REQUIRED", "必须选择平台已配置的 GitConnection")
            group = str(connection.group_id_or_org or "").strip().strip("/")
            if not group:
                return _err("SYSTEM_GIT_GROUP_REQUIRED", "所选 GitConnection 尚未配置系统资产 Git 组（group_id_or_org）")
            full_path = f"{group}/{project_name}"
            clean_remote = _clean_repository_remote(connection.host, full_path)
            initial_files = ["README.md", ".gitignore"] + (["capability.json"] if kind == "capability" else ["AGENTS.md"])
            preview = {
                "asset_type": kind,
                "repository_path": str(root),
                "repository_name": project_name,
                "repository_full_path": full_path,
                "origin": clean_remote,
                "branch": target_branch,
                "initial_files": initial_files,
                "asset_registration": (
                    {
                        "seedName": display_name,
                        "providerProjectId": "<本工具创建后返回>",
                        "pathWithNamespace": full_path,
                        "repositoryUrl": clean_remote,
                        "branch": target_branch,
                    }
                    if kind == "seed_project" else {
                        "code": normalized_code,
                        "name": display_name,
                        "gitRepository": clean_remote,
                    }
                ),
            }
            if not confirmed:
                return _confirmation_preview("create_system_asset_starter_repository", kind, full_path, preview)

            from app.git.connection import make_provider
            provider = make_provider(connection)
            existing = await provider.get_repo(full_path)
            created = existing is None
            if created:
                full_path = await provider.create_repo(
                    group_or_org=group,
                    name=project_name,
                    description=f"System {kind}: {display_name}",
                    initialize_with_readme=False,
                )
                clean_remote = _clean_repository_remote(connection.host, full_path)
                existing = await provider.get_repo(full_path)
            provider_project_id = existing.get("id") if isinstance(existing, dict) else None
            if provider_project_id is None:
                raise SystemGitError("SYSTEM_GIT_PROVIDER_PROJECT_ID_UNAVAILABLE", "Git 平台没有返回仓库 Project ID")
            authenticated_url = _authenticated_git_remote(connection, clean_remote)
            try:
                if _run_git(root.parent, "ls-remote", authenticated_url):
                    raise SystemGitError("SYSTEM_GIT_REMOTE_NOT_EMPTY", "目标远端仓库已存在提交；未写入本地目录")
                _write_starter_repository_files(root, kind, normalized_code, display_name, description)
                _run_git(root, "init", "-b", target_branch)
                _run_git(root, "add", ".")
                _run_git(
                    root, "-c", "user.name=DolphinAI System Assistant",
                    "-c", "user.email=system-assistant@localhost",
                    "commit", "-m", f"chore: initialize {project_name}",
                )
                _run_git(root, "remote", "add", "origin", clean_remote)
                push_output = _run_git(root, "-c", f"remote.origin.url={authenticated_url}", "push", "-u", "origin", target_branch)
            finally:
                del authenticated_url
            snapshot = _system_git_snapshot(str(root))
            snapshot.update({
                "asset_type": kind,
                "repository_created": created,
                "git_connection_id": connection.id,
                "provider": connection.provider,
                "repository_full_path": full_path,
                "repository_url": clean_remote.removesuffix(".git"),
                "provider_project_id": provider_project_id,
                "push_output": push_output[-1000:],
                "asset_registration": (
                    {
                        "seedName": display_name,
                        "providerProjectId": provider_project_id,
                        "pathWithNamespace": full_path,
                        "repositoryUrl": clean_remote,
                        "branch": target_branch,
                        "description": str(description or "").strip() or None,
                    }
                    if kind == "seed_project" else {"code": normalized_code, "name": display_name}
                ),
            })
            return _ok(result=_safe(snapshot))
        except SystemGitError as exc:
            return _err(exc.code, str(exc))
        except Exception as exc:  # noqa: BLE001 - provider details may contain credentials
            return _err("SYSTEM_GIT_PROVIDER_REQUEST_FAILED", "Git 平台建仓或推送失败；请检查连接权限、Git 组和网络后重试")

    @mcp.tool()
    async def create_system_capability_git_repository(
        repository_path: str,
        git_connection_id: int,
        repository_name: str | None = None,
        branch: str | None = None,
        confirmed: bool = False,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """在已配置的能力 Git 组自动建仓、绑定本地 capability 工程并推送当前分支。

        仓库组只取 GitConnection 的 group_id_or_org，不接受模型传入的任意组路径。
        默认用 capability.json 的 capability.id 作为仓库名。第一次只返回将创建的
        Git 项目、origin 和分支；调用方获得用户确认后才会调用 Git 平台建仓并 push。
        平台令牌仅在 API 调用和本次 push 的内存参数中使用，永不写入 .git/config。
        """
        try:
            resolve_identity(tenant_id, user_id)
            root = _system_git_root(repository_path)
            snapshot = _system_git_snapshot(str(root))
            capability = snapshot.get("capability") or {}
            if not capability.get("present") or not capability.get("valid"):
                return _err(
                    "SYSTEM_CAPABILITY_MANIFEST_REQUIRED",
                    "自动创建能力仓库需要仓库根目录存在有效的 capability.json",
                )
            target_branch = str(branch or snapshot.get("branch") or "").strip()
            if not target_branch or not _GIT_BRANCH_RE.fullmatch(target_branch) or target_branch.startswith("-"):
                return _err("SYSTEM_GIT_BRANCH_INVALID", "branch 必须是有效的非空 Git 分支名")
            connection = await _system_git_connection(
                resolve_identity, tenant_id, user_id, git_connection_id,
            )
            if connection is None:  # for type checkers; the ID is required above
                return _err("SYSTEM_GIT_CONNECTION_REQUIRED", "必须选择平台已配置的 GitConnection")
            group = str(connection.group_id_or_org or "").strip().strip("/")
            if not group:
                return _err(
                    "SYSTEM_GIT_GROUP_REQUIRED",
                    "所选 GitConnection 尚未配置能力 Git 组（group_id_or_org）",
                )
            project_name = _capability_repository_name(root, repository_name)
            full_path = f"{group}/{project_name}"
            clean_remote = _clean_repository_remote(connection.host, full_path)
            current_origin = str((snapshot.get("remotes") or {}).get("origin") or "")
            preview = {
                "repository_path": str(root),
                "capability": _safe(capability),
                "git_connection_id": connection.id,
                "provider": connection.provider,
                "git_group": group,
                "repository_name": project_name,
                "repository_full_path": full_path,
                "origin": clean_remote,
                "branch": target_branch,
                "head_commit": snapshot.get("head_commit"),
                "current_origin": current_origin or None,
                "is_clean": snapshot.get("is_clean"),
                "changed_files": snapshot.get("changed_files"),
            }
            if current_origin and current_origin != clean_remote:
                return _err(
                    "SYSTEM_GIT_REMOTE_ALREADY_CONFIGURED",
                    "本地仓库已有不同的 origin；请先显式确认并配置该远端，系统不会自动覆盖",
                )
            if not confirmed:
                return _confirmation_preview(
                    "create_capability_git_repository", "git_repository", full_path, preview,
                )

            try:
                from app.git.connection import make_provider
                provider = make_provider(connection)
                existing = await provider.get_repo(full_path)
                created = existing is None
                if created:
                    # The local repository already has the capability commits.
                    # An initialized README would create unrelated history and
                    # make its first push fail, so this must be an empty repo.
                    full_path = await provider.create_repo(
                        group_or_org=group,
                        name=project_name,
                        description=f"System capability: {capability.get('name') or project_name}",
                        initialize_with_readme=False,
                    )
                    clean_remote = _clean_repository_remote(connection.host, full_path)
                    existing = await provider.get_repo(full_path)
                provider_project_id = existing.get("id") if isinstance(existing, dict) else None
                if provider_project_id is None:
                    raise SystemGitError(
                        "SYSTEM_GIT_PROVIDER_PROJECT_ID_UNAVAILABLE",
                        "Git 平台没有返回仓库 Project ID；未绑定本地仓库，请稍后重试",
                    )
            except SystemGitError:
                raise
            except Exception as exc:  # noqa: BLE001 - do not leak provider internals or credentials
                raise SystemGitError(
                    "SYSTEM_GIT_PROVIDER_REQUEST_FAILED",
                    "Git 平台建仓或查询失败；请检查该连接的权限、Git 组和网络后重试",
                ) from exc

            authenticated_url = _authenticated_git_remote(connection, clean_remote)
            try:
                remote_refs = _run_git(root, "ls-remote", authenticated_url)
                if remote_refs:
                    return _err(
                        "SYSTEM_GIT_REMOTE_NOT_EMPTY",
                        "目标远端仓库已存在提交；为避免覆盖历史，未绑定也未推送",
                    )
                if current_origin:
                    _run_git(root, "remote", "set-url", "origin", clean_remote)
                else:
                    _run_git(root, "remote", "add", "origin", clean_remote)
                output = _run_git(
                    root, "-c", f"remote.origin.url={authenticated_url}",
                    "push", "-u", "origin", target_branch,
                )
            finally:
                del authenticated_url
            result = _system_git_snapshot(str(root))
            result.update({
                "git_connection_id": connection.id,
                "provider": connection.provider,
                "repository_full_path": full_path,
                "repository_url": clean_remote.removesuffix(".git"),
                "provider_project_id": provider_project_id,
                "repository_created": created,
                "push_output": output[-1000:],
            })
            return _ok(result=result)
        except SystemGitError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def configure_system_git_remote(
        repository_path: str,
        remote_url: str,
        git_connection_id: int | None = None,
        replace_existing: bool = False,
        confirmed: bool = False,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """为本地系统资产仓库配置 origin。首次调用只生成确认预览。

        远端 GitLab 项目需预先由用户/平台创建；本工具不会创建项目，也不会覆盖已有
        origin，除非 replace_existing=true 且用户明确确认。传 git_connection_id 时会使用平台
        已配置凭据验证远端可达性，凭据不会写入仓库。
        """
        try:
            resolve_identity(tenant_id, user_id)
            root = _system_git_root(repository_path)
            target = str(remote_url or "").strip()
            if not re.match(r"^(https://|ssh://|git@[^:]+:)[^\s]+$", target):
                return _err("SYSTEM_GIT_REMOTE_INVALID", "remote_url 必须是 HTTPS、SSH 或 Git SSH 地址")
            current = _run_git(root, "remote", "get-url", "origin", check=False)
            preview = {
                "repository_path": str(root),
                "current_origin": _safe_remote_url(current) if current else None,
                "target_origin": _safe_remote_url(target),
                "replace_existing": bool(replace_existing),
            }
            if not confirmed:
                return _confirmation_preview("configure_git_remote", "git_repository", str(root), preview)
            if current and current != target and not replace_existing:
                return _err("SYSTEM_GIT_REMOTE_ALREADY_CONFIGURED", "origin 已存在；如确需替换，请将 replace_existing=true 后再次确认")
            if current:
                _run_git(root, "remote", "set-url", "origin", target)
            else:
                _run_git(root, "remote", "add", "origin", target)
            connection = await _system_git_connection(
                resolve_identity, tenant_id, user_id, git_connection_id,
            )
            if connection is not None:
                authenticated_url = _authenticated_git_remote(connection, target)
                try:
                    _run_git(root, "ls-remote", authenticated_url)
                finally:
                    del authenticated_url
            result = _system_git_snapshot(str(root))
            result["git_connection_id"] = connection.id if connection is not None else None
            result["remote_verified"] = connection is not None
            return _ok(result=result)
        except SystemGitError as exc:
            return _err(exc.code, str(exc))

    @mcp.tool()
    async def push_system_git_repository(
        repository_path: str,
        branch: str | None = None,
        git_connection_id: int | None = None,
        confirmed: bool = False,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """把本地系统资产仓库当前分支推送到 origin。优先使用平台 GitConnection，首次调用只生成确认预览。"""
        try:
            resolve_identity(tenant_id, user_id)
            snapshot = _system_git_snapshot(repository_path)
            target_branch = str(branch or snapshot.get("branch") or "").strip()
            if not target_branch or not _GIT_BRANCH_RE.fullmatch(target_branch) or target_branch.startswith("-"):
                return _err("SYSTEM_GIT_BRANCH_INVALID", "branch 必须是有效的非空 Git 分支名")
            origin = str((snapshot.get("remotes") or {}).get("origin") or "")
            if not origin:
                return _err("SYSTEM_GIT_REMOTE_REQUIRED", "仓库尚未配置 origin；请先配置远端 Git 仓库")
            if not confirmed:
                return _confirmation_preview("push_git_repository", "git_repository", str(snapshot["repository_path"]), {
                    "repository_path": snapshot["repository_path"],
                    "origin": origin,
                    "branch": target_branch,
                    "head_commit": snapshot.get("head_commit"),
                    "is_clean": snapshot.get("is_clean"),
                    "changed_files": snapshot.get("changed_files"),
                    "git_connection_id": git_connection_id,
                })
            root = Path(str(snapshot["repository_path"]))
            connection = await _system_git_connection(
                resolve_identity, tenant_id, user_id, git_connection_id,
            )
            if connection is None:
                output = _run_git(root, "push", "-u", "origin", target_branch)
            else:
                authenticated_url = _authenticated_git_remote(connection, origin)
                try:
                    # ``-c`` applies only to this Git process: origin remains the
                    # clean URL in .git/config and the platform token never lands
                    # on disk.
                    output = _run_git(
                        root, "-c", f"remote.origin.url={authenticated_url}",
                        "push", "-u", "origin", target_branch,
                    )
                finally:
                    del authenticated_url
            result = _system_git_snapshot(str(root))
            result["push_output"] = output[-1000:]
            result["git_connection_id"] = connection.id if connection is not None else None
            return _ok(result=result)
        except SystemGitError as exc:
            return _err(exc.code, str(exc))

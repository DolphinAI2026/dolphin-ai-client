"""Focused contracts for the system-assistant asset-management MCP tools."""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from app.mcp_tools import system_assets
from app.models import Project, User
from app.models.collaboration import GitConnection, TenantGitConnection
from app.models.tenant import Tenant


class _FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorate(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorate


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "created", "values": {"password": "never-returned"}}


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


@pytest.fixture
def tools(monkeypatch):
    mcp = _FakeMCP()
    # The production registry is idempotent by MCP instance, so every test gets
    # its own isolated fake instance.
    system_assets.register(mcp, lambda tenant_id, user_id: (tenant_id, user_id))
    gateway = _Gateway()

    async def resolve_gateway(*_args, **_kwargs):
        return gateway

    monkeypatch.setattr(system_assets, "_gateway", resolve_gateway)
    return mcp.tools, gateway


@pytest.mark.asyncio
async def test_create_is_preview_only_until_explicit_confirmation(tools):
    registered, gateway = tools

    preview = await registered["create_system_asset"](
        "environment", {"environmentName": "dev"}, tenant_id=1, user_id=2
    )

    assert preview["ok"] is True
    assert preview["confirmation_required"] is True
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_asset_schema_exposes_canonical_enum_values_and_complete_capability_yaml_contract(tools):
    registered, _gateway = tools

    result = await registered["get_system_asset_schema"]("capability", "APP_RUNTIME")

    assert result["ok"] is True
    fields = {field["name"]: field for field in result["schema"]["create_fields"]}
    assert fields["riskLevel"]["allowed_values"] == ["GENERAL", "RESTRICTED"]
    assert fields["runtimeType"]["allowed_values"] == ["AGENT_RUNTIME", "APP_RUNTIME"]
    assert fields["yamlSchema"]["required_when"] == "runtimeType=APP_RUNTIME"
    contract = result["capability_yaml_schema"]
    assert contract["sections"]["environmentInstanceSchema"]["scope"] == "environment"
    assert contract["sections"]["applicationEnvironmentInstanceSchema"]["scope"] == "application_environment"
    assert "environmentInstanceSchema:" in contract["templates"]["without_external_parameters"]
    assert "applicationEnvironmentInstanceSchema:" in contract["templates"]["with_external_parameters"]
    assert contract["value_examples"]["application_environment_instance_values"] == {"projectKey": "approval-center"}


@pytest.mark.asyncio
async def test_system_assistant_mcp_contract_exposes_other_fixed_value_parameters(tools):
    registered, _gateway = tools

    result = await registered["get_system_assistant_mcp_contract"](
        "change_system_asset_status"
    )

    assert result["ok"] is True
    parameters = {item["name"]: item for item in result["contract"]["parameters"]}
    assert parameters["status"]["allowed_values"] == ["enabled", "disabled"]
    assert parameters["asset_type"]["allowed_values"] == [
        "seed_project", "capability", "environment", "knowledge_base", "mcp_server",
    ]


@pytest.mark.asyncio
async def test_capability_create_rejects_guessed_enum_and_unsupported_fields_before_preview(tools):
    registered, gateway = tools

    result = await registered["create_system_asset"](
        "capability",
        {
            "capabilityName": "ht-approval-center",
            "code": "ht-approval-center",
            "name": "审批中心",
            "runtimeType": "script",
            "riskLevel": "low",
            "status": "active",
            "maturity": "trial",
        },
        tenant_id=1,
        user_id=2,
    )

    assert result["ok"] is False
    assert result["error_code"] == "SYSTEM_ASSET_FIELD_VALUE_INVALID"
    invalid = {item["field"]: item for item in result["invalid_fields"]}
    assert invalid["riskLevel"]["allowed_values"] == ["GENERAL", "RESTRICTED"]
    assert invalid["runtimeType"]["allowed_values"] == ["AGENT_RUNTIME", "APP_RUNTIME"]
    assert set(result["unsupported_fields"]) == {"capabilityName", "maturity"}
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_capability_create_accepts_schema_values_before_confirmation(tools):
    registered, gateway = tools

    result = await registered["create_system_asset"](
        "capability",
        {
            "code": "ht-approval-center",
            "name": "审批中心",
            "runtimeType": "APP_RUNTIME",
            "riskLevel": "GENERAL",
            "status": "DISABLED",
            "yamlSchema": system_assets._CAPABILITY_APP_RUNTIME_SCHEMA_TEMPLATE,
        },
        tenant_id=1,
        user_id=2,
    )

    assert result["ok"] is True
    assert result["confirmation_required"] is True
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_capability_create_rejects_guessed_yaml_environment_shape_before_preview(tools):
    registered, gateway = tools

    result = await registered["create_system_asset"](
        "capability",
        {
            "code": "ht-approval-center",
            "name": "审批中心",
            "runtimeType": "APP_RUNTIME",
            "riskLevel": "GENERAL",
            "status": "DISABLED",
            "yamlSchema": "environment:\n  serviceBaseUrl: https://api.example.internal\n",
        },
        tenant_id=1,
        user_id=2,
    )

    assert result["ok"] is False
    assert result["error_code"] == "CAPABILITY_YAML_SCHEMA_INVALID"
    assert {issue["path"] for issue in result["conditional_errors"]} == {
        "environmentInstanceSchema", "applicationEnvironmentInstanceSchema",
    }
    assert "with_external_parameters" in result["capability_yaml_schema"]["templates"]
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_capability_create_accepts_full_external_parameter_schema_before_confirmation(tools):
    registered, gateway = tools

    result = await registered["create_system_asset"](
        "capability",
        {
            "code": "ht-approval-center",
            "name": "审批中心",
            "runtimeType": "APP_RUNTIME",
            "riskLevel": "GENERAL",
            "status": "DISABLED",
            "yamlSchema": system_assets._CAPABILITY_APP_RUNTIME_EXTERNAL_PARAMETERS_EXAMPLE,
        },
        tenant_id=1,
        user_id=2,
    )

    assert result["ok"] is True
    assert result["confirmation_required"] is True
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_confirmed_create_uses_user_scoped_gateway_and_redacts_result(tools):
    registered, gateway = tools

    result = await registered["create_system_asset"](
        "environment", {"environmentName": "dev"}, confirmed=True, tenant_id=1, user_id=2
    )

    assert gateway.calls == [{
        "asset_type": "environment",
        "method": "POST",
        "path": "/api/environments",
        "body": {"environmentName": "dev"},
    }]
    assert result["result"]["values"] == "<redacted>"


@pytest.mark.asyncio
async def test_environment_capability_save_never_echoes_submitted_values(tools):
    registered, gateway = tools

    result = await registered["save_environment_capability_config"](
        "app-1", "env-1", "db", {"password": "secret"}, confirmed=True, tenant_id=1, user_id=2
    )

    assert gateway.calls[0]["method"] == "PUT"
    assert gateway.calls[0]["path"].endswith("/capabilities/db/instance-config")
    assert gateway.calls[0]["body"]["values"] == {"password": "secret"}
    assert result["result"]["values"] == "<redacted>"


@pytest.mark.asyncio
async def test_deployment_environment_list_returns_k8s_summary_but_never_raw_kubeconfig(tools):
    registered, gateway = tools

    async def fake_request(**kwargs):
        gateway.calls.append(kwargs)
        if kwargs["path"] == "/api/environments":
            return {"items": [{
                "environmentId": "env-test", "environmentName": "测试环境",
                "environmentTier": "test", "status": "ENABLED",
            }]}
        assert kwargs["path"] == "/api/environments/env-test"
        return {
            "environmentId": "env-test", "environmentName": "测试环境",
            "environmentTier": "test", "status": "ENABLED",
            "infrastructureSummary": {"required": 5, "valid": 5},
            "infrastructureInstances": [{
                "infrastructureType": "DEPLOYMENT", "infrastructureKind": "K8S",
                # Simulate an upstream regression: the desktop guard must not
                # expose this even if Control Plane accidentally returns it.
                "config": {
                    "kubeConfig": "apiVersion: v1\\nusers: [very-secret]",
                    "kubeConfigSummary": {
                        "configured": True, "clusterName": "test-cluster",
                        "server": "https://k8s.test.example", "contextName": "test",
                        "caConfigured": True, "tokenConfigured": True,
                    },
                    "namespace": "test-apps",
                },
            }],
        }

    gateway.request = fake_request
    result = await registered["list_system_deployment_environments"](
        environment_tier="test", tenant_id=1, user_id=2,
    )

    assert result["ok"] is True
    deployment = result["environments"][0]["deploymentInfrastructure"][0]
    assert deployment["config"]["kubeConfig"] == "<redacted>"
    assert deployment["config"]["kubeConfigSummary"]["clusterName"] == "test-cluster"
    assert deployment["config"]["kubeConfigSummary"]["tokenConfigured"] is True
    assert deployment["config"]["namespace"] == "test-apps"


@pytest.mark.asyncio
async def test_environment_infrastructure_schema_uses_control_plane(tools):
    registered, gateway = tools

    await registered["list_environment_infrastructure_schemas"](tenant_id=1, user_id=2)

    assert gateway.calls == [{
        "asset_type": "environment",
        "method": "GET",
        "path": "/api/environments/infrastructure-form-schemas",
    }]


def test_system_asset_tool_names_cover_each_requested_asset_family():
    names = system_assets.SYSTEM_ASSET_TOOL_NAMES

    assert {
        "list_system_assets", "get_system_asset_schema", "get_system_assistant_mcp_contract",
        "get_system_asset_creation_examples", "create_system_asset", "delete_system_asset",
    }.issubset(names)
    assert {"get_environment_capability_config", "save_environment_capability_config"}.issubset(names)
    assert {
        "list_system_deployment_environments",
        "list_environment_infrastructure_schemas",
    }.issubset(names)
    assert {
        "upload_knowledge_document",
        "list_knowledge_documents",
        "get_knowledge_document",
        "delete_knowledge_document",
        "publish_knowledge_document",
        "disable_knowledge_document",
        "reindex_knowledge_document",
    }.issubset(names)
    assert {
        "create_system_skill",
        "list_system_skill_versions",
        "create_system_skill_version",
        "enable_system_skill_version",
    }.issubset(names)
    assert {
        "inspect_system_git_repository",
        "list_system_git_connections",
        "configure_system_git_remote",
        "push_system_git_repository",
        "create_system_asset_starter_repository",
        "create_system_capability_git_repository",
    }.issubset(names)


@pytest.mark.asyncio
async def test_creation_examples_read_live_seed_references_and_never_offer_them_for_copy(tools):
    registered, gateway = tools

    async def reference_request(**kwargs):
        gateway.calls.append(kwargs)
        return {"items": [{
            "seedProjectId": "seed-1", "seedName": "ht-java", "providerProjectId": 42,
            "pathWithNamespace": "orcamatrix/ht-java", "repositoryUrl": "https://git.example.com/orcamatrix/ht-java.git",
            "branch": "main", "description": "Java baseline",
        }]}

    gateway.request = reference_request
    result = await registered["get_system_asset_creation_examples"](
        "seed_project", tenant_id=1, user_id=2
    )

    assert result["ok"] is True
    assert result["reference_asset_count"] == 1
    assert result["reference_assets"] == [{
        "seedProjectId": "seed-1", "seedName": "ht-java", "providerProjectId": 42,
        "pathWithNamespace": "orcamatrix/ht-java", "repositoryUrl": "https://git.example.com/orcamatrix/ht-java.git",
        "branch": "main", "description": "Java baseline",
    }]
    assert "不得复制" in result["copy_safety"]
    assert result["schema"]["examples"]["new_git_seed"]["branch"] == "main"
    assert gateway.calls == [{
        "asset_type": "seed_project", "method": "GET", "path": "/api/seed-projects", "params": {},
    }]


@pytest.mark.asyncio
async def test_remote_mcp_servers_are_exposed_as_system_assets(tools):
    registered, gateway = tools

    result = await registered["list_system_assets"](
        "mcp_server", keyword="git", tenant_id=1, user_id=2
    )

    assert result["ok"] is True
    assert gateway.calls == [{
        "asset_type": "mcp_server",
        "method": "GET",
        "path": "/api/builder-ai/mcp-servers",
        "params": {"keyword": "git", "page": 1, "pageSize": 50},
    }]


@pytest.mark.asyncio
async def test_remote_mcp_server_status_uses_management_enable_endpoint(tools):
    registered, gateway = tools

    result = await registered["change_system_asset_status"](
        "mcp_server", "mcp-1", "enabled", 7, confirmed=True, tenant_id=1, user_id=2
    )

    assert result["ok"] is True
    assert gateway.calls == [{
        "asset_type": "mcp_server",
        "method": "POST",
        "path": "/api/builder-ai/mcp-servers/mcp-1/enable",
        "extra_headers": {"If-Match": "7"},
    }]


def _git(repo, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def capability_repository(tmp_path):
    repo = tmp_path / "approval-center"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "capability.json").write_text(json.dumps({
        "capability": {"id": "approval-center", "name": "审批中心", "version": "1.0.0"},
        "dependencies": [{"name": "platform-context", "path": "../platform-context"}],
    }), encoding="utf-8")
    _git(repo, "add", "capability.json")
    _git(repo, "commit", "-m", "initial capability")
    return repo


@pytest.mark.asyncio
async def test_inspect_system_git_repository_reports_capability_and_missing_origin(tools, capability_repository):
    registered, _gateway = tools

    result = await registered["inspect_system_git_repository"](
        str(capability_repository), tenant_id=1, user_id=2
    )

    assert result["ok"] is True
    snapshot = result["result"]
    assert snapshot["branch"] == "main"
    assert snapshot["has_origin"] is False
    assert snapshot["capability"] == {
        "present": True,
        "valid": True,
        "id": "approval-center",
        "name": "审批中心",
        "version": "1.0.0",
        "dependencies": [{"name": "platform-context", "path": "../platform-context"}],
    }


@pytest.mark.asyncio
async def test_configure_system_git_remote_requires_confirmation(tools, capability_repository):
    registered, _gateway = tools
    remote = "https://git.example.com/orcamatrix/approval-center.git"

    preview = await registered["configure_system_git_remote"](
        str(capability_repository), str(remote), tenant_id=1, user_id=2
    )
    assert preview["confirmation_required"] is True
    assert _git_remote(capability_repository) == ""

    applied = await registered["configure_system_git_remote"](
        str(capability_repository), str(remote), confirmed=True, tenant_id=1, user_id=2
    )
    assert applied["ok"] is True
    assert _git_remote(capability_repository) == remote


@pytest.mark.asyncio
async def test_tenant_git_connection_is_listed_and_scope_prevents_id_collision(tools, db_session, monkeypatch):
    registered, _gateway = tools
    tenant = Tenant(tenant_name="git-tenant", tenant_code="git-tenant")
    user = User(username="git-user", hashed_password="x")
    db_session.add_all([tenant, user])
    await db_session.flush()
    project = Project(name="legacy-project", user_id=user.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()
    db_session.add_all([
        TenantGitConnection(
            tenant_id=tenant.id, provider="gitlab", host="https://git.example.com",
            access_token_enc="tenant-token", group_id_or_org="platform/assets", status="connected",
        ),
        GitConnection(
            project_id=project.id, provider="gitlab", host="https://git.example.com",
            access_token_enc="project-token", group_id_or_org="legacy/project", status="connected",
        ),
    ])
    await db_session.commit()
    monkeypatch.setattr(system_assets, "AsyncSessionLocal", lambda: _SessionContext(db_session))

    listed = await registered["list_system_git_connections"](tenant_id=tenant.id, user_id=user.id)
    assert {(item["connection_scope"], item["id"]) for item in listed["connections"]} == {
        ("tenant", 1), ("project", 1),
    }
    tenant_connection = await system_assets._system_git_connection(
        lambda tenant_id, _user_id: (tenant_id, user.id), tenant.id, user.id, 1, "tenant",
    )
    assert isinstance(tenant_connection, TenantGitConnection)
    project_connection = await system_assets._system_git_connection(
        lambda tenant_id, _user_id: (tenant_id, user.id), tenant.id, user.id, 1, "project",
    )
    assert isinstance(project_connection, GitConnection)
    with pytest.raises(system_assets.SystemGitError, match="connection_scope"):
        await system_assets._system_git_connection(
            lambda tenant_id, _user_id: (tenant_id, user.id), tenant.id, user.id, 1,
        )


@pytest.mark.asyncio
async def test_deployment_git_default_is_used_when_tenant_has_no_override(tools, db_session, monkeypatch):
    registered, _gateway = tools
    tenant = Tenant(tenant_name="default-git-tenant", tenant_code="default-git-tenant")
    user = User(username="default-git-user", hashed_password="x")
    db_session.add_all([tenant, user])
    await db_session.commit()
    monkeypatch.setattr(system_assets, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    monkeypatch.setattr(system_assets.settings, "system_git_default_provider", "gitlab")
    monkeypatch.setattr(system_assets.settings, "system_git_default_host", "https://git.example.com")
    monkeypatch.setattr(system_assets.settings, "system_git_default_access_token", "deployment-secret")
    monkeypatch.setattr(system_assets.settings, "system_git_default_group_or_org", "platform/assets")

    listed = await registered["list_system_git_connections"](tenant_id=tenant.id, user_id=user.id)
    assert listed["connections"] == [{
        "id": 0,
        "connection_scope": "deployment_default",
        "provider": "gitlab",
        "host": "https://git.example.com",
        "group_id_or_org": "platform/assets",
        "status": "connected",
        "source": "deployment_config",
    }]
    resolved = await system_assets._system_git_connection(
        lambda tenant_id, _user_id: (tenant_id, user.id), tenant.id, user.id, 0, "deployment_default",
    )
    assert isinstance(resolved, system_assets.DeploymentGitConnection)
    assert resolved.access_token_enc != "deployment-secret"


@pytest.mark.asyncio
async def test_control_plane_git_default_exposes_typed_asset_groups(tools, db_session, monkeypatch):
    registered, gateway = tools
    tenant = Tenant(tenant_name="broker-git-tenant", tenant_code="broker-git-tenant")
    user = User(username="broker-git-user", hashed_password="x")
    db_session.add_all([tenant, user])
    await db_session.commit()
    monkeypatch.setattr(system_assets, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    monkeypatch.setenv("DOLPHIN_SYSTEM_GIT_ENABLED", "true")

    async def broker_connection(**kwargs):
        gateway.calls.append(kwargs)
        return {
            "id": 0,
            "connectionScope": "control_plane_default",
            "provider": "gitlab",
            "host": "https://git.example.com",
            "assetGroups": {
                "seed_project": "dolphin-code/seeds",
                "capability": "dolphin-code/capabilities",
            },
            "defaultBranch": "main",
        }

    monkeypatch.setattr(gateway, "request", broker_connection)

    listed = await registered["list_system_git_connections"](tenant_id=tenant.id, user_id=user.id)

    assert listed["connection_status"] == "ready"
    assert listed["connections"] == [{
        "id": 0,
        "connection_scope": "control_plane_default",
        "provider": "gitlab",
        "host": "https://git.example.com",
        "asset_groups": {
            "seed_project": "dolphin-code/seeds",
            "capability": "dolphin-code/capabilities",
        },
        "default_branch": "main",
        "status": "connected",
        "source": "control_plane",
    }]


@pytest.mark.asyncio
async def test_empty_git_list_explains_disabled_broker_without_claiming_platform_is_empty(
    tools, db_session, monkeypatch,
):
    registered, _gateway = tools
    tenant = Tenant(tenant_name="disabled-git-tenant", tenant_code="disabled-git-tenant")
    user = User(username="disabled-git-user", hashed_password="x")
    db_session.add_all([tenant, user])
    await db_session.commit()
    monkeypatch.setattr(system_assets, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    monkeypatch.delenv("DOLPHIN_SYSTEM_GIT_ENABLED", raising=False)

    listed = await registered["list_system_git_connections"](tenant_id=tenant.id, user_id=user.id)

    assert listed["connections"] == []
    assert listed["connection_status"] == "broker_disabled"
    assert "不代表平台没有 Git" in listed["message"]


@pytest.mark.asyncio
async def test_control_plane_repository_broker_routes_create_by_asset_type(tools, monkeypatch):
    _registered, gateway = tools
    response = {
        "provider": "gitlab",
        "providerProjectId": "501",
        "pathWithNamespace": "dolphin-code/capabilities/approval-center",
        "repositoryUrl": "https://git.example.com/dolphin-code/capabilities/approval-center.git",
        "branch": "main",
        "accessToken": "one-process-only",
    }

    async def create_repository(**kwargs):
        gateway.calls.append(kwargs)
        return response

    monkeypatch.setattr(gateway, "request", create_repository)
    access = await system_assets._control_plane_git_repository_access(
        lambda tenant_id, user_id: (tenant_id, user_id),
        1,
        2,
        action="create",
        asset_type="capability",
        repository_name="approval-center",
    )

    assert gateway.calls[0]["body"] == {
        "assetType": "capability",
        "repositoryName": "approval-center",
    }
    assert access.path_with_namespace == "dolphin-code/capabilities/approval-center"
    assert access.connection.access_token_enc != "one-process-only"
    assert "accessToken" not in response


@pytest.mark.asyncio
async def test_create_capability_git_repository_previews_platform_group_and_push(tools, capability_repository, monkeypatch):
    registered, _gateway = tools
    connection = SimpleNamespace(
        id=42,
        provider="gitlab",
        host="https://git.example.com",
        group_id_or_org="orcamatrix/capabilities",
    )

    async def fake_connection(*_args, **_kwargs):
        return connection

    monkeypatch.setattr(system_assets, "_system_git_connection", fake_connection)
    preview = await registered["create_system_capability_git_repository"](
        str(capability_repository), git_connection_id=42, tenant_id=1, user_id=2,
    )

    assert preview["confirmation_required"] is True
    assert preview["preview"]["repository_full_path"] == "orcamatrix/capabilities/approval-center"
    assert preview["preview"]["origin"] == "https://git.example.com/orcamatrix/capabilities/approval-center.git"
    assert _git_remote(capability_repository) == ""


@pytest.mark.asyncio
async def test_create_capability_git_repository_creates_empty_remote_then_pushes(tools, capability_repository, monkeypatch):
    registered, _gateway = tools
    connection = SimpleNamespace(
        id=42,
        provider="gitlab",
        host="https://git.example.com",
        group_id_or_org="orcamatrix/capabilities",
    )

    async def fake_connection(*_args, **_kwargs):
        return connection

    class FakeProvider:
        async def get_repo(self, _path):
            return None if not getattr(self, "created", False) else {"id": 9527}

        async def create_repo(self, **kwargs):
            assert kwargs["initialize_with_readme"] is False
            assert kwargs["group_or_org"] == "orcamatrix/capabilities"
            self.created = True
            return "orcamatrix/capabilities/approval-center"

    import app.git.connection as git_connection
    monkeypatch.setattr(system_assets, "_system_git_connection", fake_connection)
    monkeypatch.setattr(system_assets, "_authenticated_git_remote", lambda *_args: "https://ephemeral-token@git.example.com/orcamatrix/capabilities/approval-center.git")
    monkeypatch.setattr(git_connection, "make_provider", lambda _connection: FakeProvider())
    real_run_git = system_assets._run_git

    def fake_run_git(root, *args, check=True):
        if args and args[0] == "ls-remote":
            return ""
        if "push" in args:
            return "To https://git.example.com/orcamatrix/capabilities/approval-center.git\n * [new branch] main -> main"
        return real_run_git(root, *args, check=check)

    monkeypatch.setattr(system_assets, "_run_git", fake_run_git)
    result = await registered["create_system_capability_git_repository"](
        str(capability_repository), git_connection_id=42, confirmed=True, tenant_id=1, user_id=2,
    )

    assert result["ok"] is True
    assert result["result"]["repository_created"] is True
    assert result["result"]["provider_project_id"] == 9527
    assert result["result"]["repository_url"] == "https://git.example.com/orcamatrix/capabilities/approval-center"
    assert _git_remote(capability_repository) == "https://git.example.com/orcamatrix/capabilities/approval-center.git"


def _git_remote(repo) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        check=False, capture_output=True, text=True,
    )
    return result.stdout.strip()


@pytest.mark.asyncio
async def test_starter_repository_creates_new_capability_repo_only_after_confirmation(tools, tmp_path, monkeypatch):
    registered, _gateway = tools
    connection = SimpleNamespace(
        id=42,
        provider="gitlab",
        host="https://git.example.com",
        group_id_or_org="orcamatrix/capabilities",
    )

    async def fake_connection(*_args, **_kwargs):
        return connection

    class FakeProvider:
        created = False

        async def get_repo(self, _path):
            return {"id": 9527} if self.created else None

        async def create_repo(self, **kwargs):
            assert kwargs["group_or_org"] == "orcamatrix/capabilities"
            assert kwargs["initialize_with_readme"] is False
            self.created = True
            return "orcamatrix/capabilities/approval-center"

    import app.git.connection as git_connection
    monkeypatch.setattr(system_assets, "_system_git_connection", fake_connection)
    monkeypatch.setattr(system_assets, "_authenticated_git_remote", lambda *_args: "https://ephemeral-token@git.example.com/orcamatrix/capabilities/approval-center.git")
    monkeypatch.setattr(git_connection, "make_provider", lambda _connection: FakeProvider())
    real_run_git = system_assets._run_git

    def fake_run_git(root, *args, check=True):
        if args and args[0] == "ls-remote":
            return ""
        if "push" in args:
            return "To https://git.example.com/orcamatrix/capabilities/approval-center.git"
        return real_run_git(root, *args, check=check)

    monkeypatch.setattr(system_assets, "_run_git", fake_run_git)
    repo = tmp_path / "approval-center"
    preview = await registered["create_system_asset_starter_repository"](
        "capability", str(repo), 42, "approval-center", "审批中心", tenant_id=1, user_id=2,
    )
    assert preview["confirmation_required"] is True
    assert not repo.exists()

    result = await registered["create_system_asset_starter_repository"](
        "capability", str(repo), 42, "approval-center", "审批中心", confirmed=True, tenant_id=1, user_id=2,
    )
    assert result["ok"] is True
    assert (repo / "capability.json").is_file()
    assert _git(repo, "rev-parse", "--verify", "HEAD") is None
    assert _git_remote(repo) == "https://git.example.com/orcamatrix/capabilities/approval-center.git"
    assert result["result"]["provider_project_id"] == 9527
    assert result["result"]["asset_registration"] == {"code": "approval-center", "name": "审批中心"}


def test_control_plane_asset_requests_forward_the_authenticated_tenant_header():
    gateway = system_assets.AssetGateway(
        control_plane_base="https://control-plane.example",
        control_plane_token="control-token",
        management_base="https://management.example",
        management_token="management-token",
        control_plane_tenant_id="tenant-from-session",
    )

    headers = gateway.request_headers(use_management=False)

    assert headers == {
        "Authorization": "Bearer control-token",
        "X-Tenant-Id": "tenant-from-session",
    }


@pytest.mark.asyncio
async def test_capability_status_uses_explicit_enable_endpoint(tools):
    registered, gateway = tools

    await registered["change_system_asset_status"](
        "capability", "cap-1", "enabled", 3, confirmed=True, tenant_id=1, user_id=2
    )

    assert gateway.calls == [{
        "asset_type": "capability",
        "method": "POST",
        "path": "/api/capabilities/cap-1/enable",
        "body": {"status": "enabled", "object_version_number": 3, "reason": None},
    }]

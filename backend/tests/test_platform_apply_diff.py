"""Phase E Task 2 — SPEC diff → ConfigDiff 桥 + execute_platform_apply 测试。

不真踩 aPaaS 平台 API：dry_run mode 直接走 diff 摘要；真 apply 路径用 monkeypatch
把 IncrementalExecutor.execute_diff 替换成 AsyncMock，验证调用链。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.incremental_executor import ExecutionResult
from app.proposal.platform_apply import execute_platform_apply, spec_diff_to_config_diff
from app.builder_spec.schema import (
    Completeness,
    FieldSpec,
    Goal,
    ObjectSpec,
    Phase,
    Role,
    Spec,
    derive_completeness,
)


def _make_spec(*, spec_id: str, with_extra_field: bool = False) -> Spec:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    fields = [
        FieldSpec(code="amount", name="金额", type="数字", confirmed=True),
    ]
    if with_extra_field:
        fields.append(FieldSpec(code="remark", name="备注", type="单行输入", confirmed=True))
    s = Spec(
        id=spec_id,
        application_id=1,
        version=1,
        phase=Phase.DRAFTING,
        goal=Goal(title="测试", summary="s", business_problem="b", confirmed=True),
        roles=[Role(code="admin", name="管理员", scope="ALL", confirmed=True)],
        objects=[ObjectSpec(code="t_order", name="订单", fields=fields, confirmed=True)],
        dicts=[],
        permissions=[],
        completeness=Completeness(),
        created_at=now,
        updated_at=now,
        created_by=1,
    )
    s.completeness = derive_completeness(s)
    return s


def test_canonical_none_treated_as_empty():
    """canonical=None（全新应用）→ diff 全部是 add ops（model + role）"""
    draft = _make_spec(spec_id="spec_draft_v1")
    diff = spec_diff_to_config_diff(canonical=None, draft=draft)

    assert diff.has_changes is True
    # 至少有 1 个 model 新增 + 1 个 role 新增
    assert len(diff.model_changes) == 1
    assert diff.model_changes[0].change_type.value == "added"
    assert len(diff.role_changes) == 1
    assert diff.role_changes[0].change_type.value == "added"


@pytest.mark.asyncio
async def test_dry_run_does_not_call_platform(monkeypatch):
    """dry_run=True 时不构造 APaaSClient / IncrementalExecutor，仅返回 diff 摘要"""
    # spy：如果有人尝试构造 client / executor 就让测试 fail
    client_calls = []
    executor_calls = []
    monkeypatch.setattr(
        "app.proposal.platform_apply.APaaSClient",
        lambda *a, **kw: client_calls.append((a, kw)) or pytest.fail("不该构造 APaaSClient"),
    )
    monkeypatch.setattr(
        "app.proposal.platform_apply.IncrementalExecutor",
        lambda *a, **kw: executor_calls.append((a, kw)) or pytest.fail("不该构造 IncrementalExecutor"),
    )

    draft = _make_spec(spec_id="spec_draft_v1")
    application = MagicMock()  # dry_run 不会访问任何字段，所以 magic mock 即可

    result = await execute_platform_apply(
        application=application, canonical=None, draft=draft, dry_run=True,
    )

    assert isinstance(result, ExecutionResult)
    # 至少 models / roles 各 1 条 dry-run 摘要
    assert any("dry-run" in m for m in result.results.get("models", []))
    assert any("dry-run" in m for m in result.results.get("roles", []))
    assert client_calls == []
    assert executor_calls == []


@pytest.mark.asyncio
async def test_platform_apply_calls_executor(monkeypatch):
    """happy path：mock IncrementalExecutor.execute_diff，验证整条链路"""
    fake_result = ExecutionResult()
    fake_result.add_success("models", "created t_order")

    captured: dict = {}

    class FakeExecutor:
        def __init__(self, *, client, app_id, app_name, target_config):
            captured["client"] = client
            captured["app_id"] = app_id
            captured["app_name"] = app_name
            captured["target_config"] = target_config

        async def execute_diff(self, diff):
            captured["diff"] = diff
            return fake_result

    class FakeClient:
        def __init__(self, *, base_url, tenant_id, token):
            captured["base_url"] = base_url
            captured["tenant_id"] = tenant_id
            captured["token"] = token

    monkeypatch.setattr("app.proposal.platform_apply.APaaSClient", FakeClient)
    monkeypatch.setattr("app.proposal.platform_apply.IncrementalExecutor", FakeExecutor)

    draft = _make_spec(spec_id="spec_draft_v1", with_extra_field=True)

    application = MagicMock()
    application.id = 42
    application.platform_url = "https://apaas.test"
    application.platform_token = "tok123"
    application.platform_tenant_id = "tenant_a"
    application.apaas_app_id = "app_remote_001"
    application.app_name = "TestApp"

    result = await execute_platform_apply(
        application=application, canonical=None, draft=draft, dry_run=False,
    )

    assert result is fake_result
    assert captured["base_url"] == "https://apaas.test"
    assert captured["token"] == "tok123"
    assert captured["app_id"] == "app_remote_001"
    assert captured["app_name"] == "TestApp"
    assert captured["diff"].has_changes is True


@pytest.mark.asyncio
async def test_platform_apply_raises_when_platform_unbound():
    """application 未绑定平台时 raise RuntimeError"""
    draft = _make_spec(spec_id="spec_draft_v1")
    application = MagicMock()
    application.id = 99
    application.platform_url = None
    application.platform_token = None
    application.apaas_app_id = None

    with pytest.raises(RuntimeError, match="未连接 aPaaS 平台"):
        await execute_platform_apply(
            application=application, canonical=None, draft=draft, dry_run=False,
        )

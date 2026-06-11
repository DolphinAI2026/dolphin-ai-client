from __future__ import annotations

import pytest

from app.routes.applications.generate import _mark_stage_completed_keys
from app.routes import generation_steps


def test_stage5_marks_only_created_workflow_indices():
    config = {
        "data": {
            "workflows": [
                {"name": "立项审批", "form_code": "project_form"},
                {"name": "结项审批", "form_code": "closure_form"},
                {"name": "变更审批", "form_code": "change_form"},
            ]
        }
    }

    keys = _mark_stage_completed_keys(
        config,
        5,
        {"created": 2, "total": 3, "created_indices": [0, 2]},
    )

    assert keys == {"create_workflow:0", "create_workflow:2"}


def test_build_steps_includes_workflows_before_permissions():
    config = {
        "data": {
            "forms": [{"name": "项目立项", "modelCode": "project"}],
            "models": [{"name": "项目", "code": "project"}],
            "workflows": [{"name": "项目立项审批流", "form_code": "project_form"}],
        }
    }
    state = {
        "steps_completed": ["create_app", "create_model:0", "create_form:0"],
        "step_errors": {},
    }

    steps = generation_steps._build_steps(config, state, "apaas1")
    keys = [step.key for step in steps]

    assert "create_workflow:0" in keys
    assert keys.index("create_workflow:0") < keys.index("configure_permissions")
    workflow_step = next(step for step in steps if step.key == "create_workflow:0")
    assert workflow_step.status == "pending"
    assert workflow_step.deps_met is True
    permission_step = next(step for step in steps if step.key == "configure_permissions")
    assert permission_step.deps_met is False


def test_workflows_are_critical_when_declared():
    config = {"data": {"workflows": [{"name": "项目立项审批流", "form_code": "project_form"}]}}

    assert "create_workflow:0" in generation_steps._critical_step_keys(config)


@pytest.mark.asyncio
async def test_reality_reconcile_marks_platform_workflows(monkeypatch):
    class _App:
        id = 123
        apaas_app_id = "apaas1"

    class _Client:
        async def query_models(self, app_id, with_fields=False):
            return []

        async def query_roles(self, app_id):
            return []

        async def query_dicts(self, app_id):
            return []

        async def query_menus(self, app_id):
            return []

        async def list_processes(self, app_id):
            return [
                {
                    "processName": "项目立项审批流",
                    "processCode": "proc_project_form",
                }
            ]

    async def _fake_resolve_env_and_client(app, db):
        return _Client(), object()

    from app.routes.applications import generate

    monkeypatch.setattr(generate, "_resolve_env_and_client", _fake_resolve_env_and_client)
    generation_steps._REALITY_CACHE.clear()

    keys = await generation_steps._reality_completed_step_keys(
        _App(),
        {"data": {"workflows": [{"name": "项目立项审批流", "form_code": "project_form"}]}},
        db=object(),
    )

    assert "create_workflow:0" in keys

from datetime import datetime, timezone

from app.routes.online_coding import (
    EMPTY_REPO_IMPORT_ERROR,
    _build_ide_workspace_context,
    _is_repo_imported,
    _mark_empty_repo_import,
    _public_workspace,
)


def _base_meta() -> dict:
    now = datetime(2026, 4, 28, tzinfo=timezone.utc).isoformat()
    return {
        "id": "oc_empty",
        "repo_url": "https://github.com/example/empty.git",
        "task": "从 0 到 1 开发一个头像上传组件",
        "user_id": 1,
        "tenant_id": 1,
        "status": "repo_importing",
        "sandbox_status": "importing",
        "created_at": now,
        "updated_at": now,
    }


def test_empty_repo_import_is_ready_for_ide():
    meta = _mark_empty_repo_import(_base_meta(), branch="main")

    assert meta["status"] == "repo_imported"
    assert meta["sandbox_status"] == "repo_ready"
    assert meta["file_count"] == 0
    assert meta["files"] == []
    assert meta["import_error"] is None
    assert _is_repo_imported(meta) is True

    public = _public_workspace(meta)
    assert public.status == "repo_imported"
    assert public.sandbox_status == "repo_ready"
    assert public.import_error is None
    assert "初始化首版工程" in public.next_steps[0]


def test_legacy_empty_repo_failure_is_treated_as_imported():
    meta = _base_meta()
    meta.update({
        "status": "import_failed",
        "sandbox_status": "not_configured",
        "file_count": 0,
        "files": [],
        "import_error": EMPTY_REPO_IMPORT_ERROR,
    })

    assert _is_repo_imported(meta) is True
    public = _public_workspace(meta)
    assert public.status == "repo_imported"
    assert public.sandbox_status == "repo_ready"
    assert public.import_error is None


def test_empty_repo_ide_context_guides_zero_to_one_development(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    payload = _build_ide_workspace_context(repo_dir, "开发一个头像上传组件")

    assert payload["file_count"] == 0
    assert payload["read_files"] == []
    assert "EMPTY_REPO: true" in payload["context"]
    assert "0-1 新项目" in payload["context"]

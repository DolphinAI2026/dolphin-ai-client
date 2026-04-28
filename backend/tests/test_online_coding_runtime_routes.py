from datetime import datetime, timezone
from pathlib import Path

from app.coding.preview_runtime.contracts import PreviewRuntimeState, PreviewRuntimeStatus
from app.routes.online_coding_runtime import (
    _preview_state_payload,
    _rewrite_preview_body,
    _rewrite_preview_location,
)


def test_preview_state_payload_serializes_runtime_state():
    now = datetime(2026, 4, 28, tzinfo=timezone.utc)
    state = PreviewRuntimeState(
        workspace_id="oc_payload",
        status=PreviewRuntimeStatus.RUNNING,
        runner="local",
        working_dir=Path("/tmp/workspace/repo"),
        port=31000,
        preview_url="http://builder/api/online-coding/workspaces/oc_payload/preview/?port=31000",
        pid=123,
        log_path=Path("/tmp/runtime/oc_payload/preview.log"),
        command=["npm", "run", "dev"],
        started_at=now,
        updated_at=now,
    )

    payload = _preview_state_payload(state)

    assert payload == {
        "workspace_id": "oc_payload",
        "status": "running",
        "runner": "local",
        "working_dir": "/tmp/workspace/repo",
        "port": 31000,
        "preview_url": "http://builder/api/online-coding/workspaces/oc_payload/preview/?port=31000",
        "pid": 123,
        "log_path": "/tmp/runtime/oc_payload/preview.log",
        "command": ["npm", "run", "dev"],
        "error": None,
        "started_at": "2026-04-28T00:00:00+00:00",
        "updated_at": "2026-04-28T00:00:00+00:00",
    }


def test_rewrite_preview_location_keeps_redirect_inside_workspace_proxy():
    assert _rewrite_preview_location("/ai-builder/", "oc_payload", 31000) == (
        "/api/online-coding/workspaces/oc_payload/preview/ai-builder/?port=31000"
    )


def test_rewrite_preview_body_prefixes_vite_absolute_asset_paths():
    body = b'''
<!doctype html>
<script type="module" src="/ai-builder/@vite/client"></script>
<script type="module" src="/ai-builder/src/main.ts"></script>
'''

    rewritten = _rewrite_preview_body(body, "text/html", "oc_payload", "ai-builder/")

    assert b'"/api/online-coding/workspaces/oc_payload/preview/ai-builder/@vite/client' in rewritten
    assert b'"/api/online-coding/workspaces/oc_payload/preview/ai-builder/src/main.ts' in rewritten

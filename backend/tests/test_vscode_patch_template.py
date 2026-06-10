from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_apply_edits_uses_shared_ide_headers_helper():
    template = (repo_root() / "scripts" / "patch_vscode_chat_fallback.template.txt").read_text(
        encoding="utf-8"
    )

    assert "const _ideHeaders=()=>(" in template
    assert 'headers:{..._ideHeaders(),"Content-Type":"application/json"}' in template
    assert 'headers:{..._ghdr,"Content-Type":"application/json"}' not in template


def test_write_path_does_not_depend_on_minified_vscode_workspace_tokens():
    template = (repo_root() / "scripts" / "patch_vscode_chat_fallback.template.txt").read_text(
        encoding="utf-8"
    )

    assert "ie.get(Qe)" not in template
    assert "ie.get(Me)" not in template


def test_chat_enable_default_agent_matches_ruijing_participant_id():
    script = (repo_root() / "scripts" / "patch_vscode_chat_enable.js").read_text(
        encoding="utf-8"
    )
    package_json = (repo_root() / "extensions" / "ruijing-ai" / "package.json").read_text(
        encoding="utf-8"
    )

    assert '"id": "ruijing-ai.chat"' in package_json
    assert "id: 'ruijing-ai.chat'" in script
    assert "name: '睿鲸AI'" in script
    assert "id: 'ruijing', name: 'RuijingAI'" not in script


def test_chat_enable_patches_embedded_workbench_default_agent():
    script = (repo_root() / "scripts" / "patch_vscode_chat_enable.js").read_text(
        encoding="utf-8"
    )

    assert 'extensionId:"GitHub.copilot"' in script
    assert 'extensionId:"apaas-builder.ruijing-ai"/*patched:embedded-default-agent*/' in script
    assert 'provider:{default:{id:"ruijing-ai.chat",name:"睿鲸AI"}' in script


def test_fallback_template_avoids_internal_extension_identifier_constructor():
    template = (repo_root() / "scripts" / "patch_vscode_chat_fallback.template.txt").read_text(
        encoding="utf-8"
    )

    assert "new Ii(String(_id))" not in template
    assert "patched:no-extension-id-constructor" in template


def test_patch_all_runs_chat_fallback_after_chat_enable():
    script = (repo_root() / "scripts" / "patch_all.js").read_text(encoding="utf-8")

    enable_idx = script.index("patch_vscode_chat_enable.js")
    fallback_idx = script.index("patch_vscode_chat_fallback.js")
    assert enable_idx < fallback_idx

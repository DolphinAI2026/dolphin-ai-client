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

    branding_idx = script.index("patch_vscode_branding.js")
    enable_idx = script.index("patch_vscode_chat_enable.js")
    fallback_idx = script.index("patch_vscode_chat_fallback.js")
    assert branding_idx < enable_idx
    assert enable_idx < fallback_idx


def test_ide_patch_disables_workspace_trust_prompt():
    patch_all = (repo_root() / "scripts" / "patch_all.js").read_text(encoding="utf-8")
    entrypoint = (repo_root() / "deploy" / "docker" / "entrypoint.sh").read_text(
        encoding="utf-8"
    )

    for source in (patch_all, entrypoint):
        assert "security.workspace.trust.enabled" in source
        assert "security.workspace.trust.startupPrompt" in source
        assert "security.workspace.trust.untrustedFiles" in source


def test_branding_patch_accepts_explicit_code_server_path():
    script = (repo_root() / "scripts" / "patch_vscode_branding.js").read_text(
        encoding="utf-8"
    )

    assert "process.argv.slice(2)" in script
    assert "args[i] === '--code-server-path'" in script
    assert "resolve(explicitPath)" in script


def test_branding_patch_waits_for_late_welcome_dom():
    script = (repo_root() / "scripts" / "patch_vscode_branding.js").read_text(
        encoding="utf-8"
    )

    assert "new MutationObserver" in script
    assert "maxAttempts = 240" in script
    assert "function scheduleDecorate()" in script
    assert "if (decorateWelcome())" in script
    assert "observer.disconnect()" in script
    assert "attempts >= 20" not in script


def test_code_server_resolver_discovers_container_opt_path():
    script = (repo_root() / "scripts" / "lib" / "codeServerResolver.js").read_text(
        encoding="utf-8"
    )

    assert "'/opt/code-server'" in script


def test_deploy_cloud_uploads_all_patch_all_dependencies():
    script = (repo_root() / "scripts" / "deploy_cloud.py").read_text(encoding="utf-8")

    assert '"patch_vscode_chat_fallback.js"' in script
    assert '"patch_vscode_chat_fallback.template.txt"' in script

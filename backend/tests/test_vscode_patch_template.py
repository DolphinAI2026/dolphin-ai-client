from pathlib import Path


def test_apply_edits_uses_shared_ide_headers_helper():
    template = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "patch_vscode_chat_fallback.template.txt"
    ).read_text(encoding="utf-8")

    assert "const _ideHeaders=()=>(" in template
    assert 'headers:{..._ideHeaders(),"Content-Type":"application/json"}' in template
    assert 'headers:{..._ghdr,"Content-Type":"application/json"}' not in template


def test_write_path_does_not_depend_on_minified_vscode_workspace_tokens():
    template = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "patch_vscode_chat_fallback.template.txt"
    ).read_text(encoding="utf-8")

    assert "ie.get(Qe)" not in template
    assert "ie.get(Me)" not in template

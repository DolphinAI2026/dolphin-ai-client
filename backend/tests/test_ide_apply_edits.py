from app.routes.coding import IDEFileEdit, _apply_ide_edits_to_path


def test_apply_ide_edits_writes_files(tmp_path):
    result = _apply_ide_edits_to_path(
        tmp_path,
        [
            IDEFileEdit(path="src/main.ts", content="console.log('ok')\n", action="write"),
            IDEFileEdit(path="README.md", content="# Demo\n", action="create"),
        ],
    )

    assert result["skipped"] == []
    assert result["applied"] == [
        {"path": "src/main.ts", "action": "write"},
        {"path": "README.md", "action": "create"},
    ]
    assert (tmp_path / "src" / "main.ts").read_text(encoding="utf-8") == "console.log('ok')\n"
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# Demo\n"


def test_apply_ide_edits_rejects_parent_traversal(tmp_path):
    result = _apply_ide_edits_to_path(
        tmp_path,
        [IDEFileEdit(path="../outside.txt", content="bad", action="write")],
    )

    assert result["applied"] == []
    assert result["skipped"][0]["path"] == "../outside.txt"
    assert "Invalid target path" in result["skipped"][0]["reason"]
    assert not (tmp_path.parent / "outside.txt").exists()

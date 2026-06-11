"""read_query 工作区只读工具(workspace_read_tools)单测。"""
import pytest

from app.coding.workspace_read_tools import (
    execute_workspace_tool,
    list_workspace_files,
    read_workspace_file,
    search_workspace_code,
)


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "page.vue").write_text("<template>\n  <div>hello</div>\n</template>\n", encoding="utf-8")
    (tmp_path / "src" / "api.js").write_text("export function getList() {}\n", encoding="utf-8")
    (tmp_path / ".workspace.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "i.js").write_text("junk", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00binary")
    return tmp_path


def test_list_excludes_hidden_and_node_modules(ws):
    out = list_workspace_files(ws)
    assert "src/page.vue" in out and "src/api.js" in out
    assert "node_modules" not in out and ".workspace.json" not in out


def test_read_file_ok_binary_missing_and_escape(ws):
    assert "<div>hello</div>" in read_workspace_file(ws, "src/page.vue")
    assert read_workspace_file(ws, "logo.png").startswith("Error:")
    assert read_workspace_file(ws, "src/nope.js").startswith("Error: 文件不存在")
    # 路径越界走 execute 包装 → 错误字符串而不是异常
    assert execute_workspace_tool(ws, "read_workspace_file", {"file_path": "../../etc/passwd"}).startswith("Error:")


def test_read_file_rejects_sibling_prefix_escape(ws):
    """`ws` 与 `ws-other` 这种同名前缀目录不能靠字符串 startswith 放行。"""
    sibling = ws.parent / f"{ws.name}-other"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("secret", encoding="utf-8")
    out = execute_workspace_tool(ws, "read_workspace_file", {"file_path": f"../{sibling.name}/secret.txt"})
    assert out.startswith("Error: 文件路径越界")


def test_read_file_truncates_long_content(ws):
    (ws / "big.txt").write_text("x" * 9000, encoding="utf-8")
    out = read_workspace_file(ws, "big.txt")
    assert "已截断" in out and len(out) < 9000


def test_search_code_hits_with_line_numbers(ws):
    out = search_workspace_code(ws, r"getList")
    assert "src/api.js:1:" in out
    assert search_workspace_code(ws, r"不存在的串") == "(无匹配)"
    assert search_workspace_code(ws, r"[bad").startswith("Error: 正则不合法")


def test_execute_dispatch_unknown_tool(ws):
    assert execute_workspace_tool(ws, "rm_rf", {}).startswith("Error: 未知")


def test_search_workspace_hits_structured(ws):
    import re

    from app.coding.workspace_read_tools import search_workspace_hits

    hits, truncated = search_workspace_hits(ws, re.compile(re.escape("GETLIST"), re.IGNORECASE))
    assert truncated is False
    assert hits == [{"path": "src/api.js", "line": 1, "text": "export function getList() {}"}]

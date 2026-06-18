from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "templates" / "cli-generated" / "form-page-web" / "public" / "index.html"
)


def test_dev_index_html_exists():
    assert TEMPLATE.is_file(), f"missing dev shim template: {TEMPLATE}"


def test_dev_index_html_injects_request_and_df_shim():
    html = TEMPLATE.read_text(encoding="utf-8")
    # $request shim present and exposed both globally and on the Vue prototype
    assert "window.$request" in html
    assert "Vue.prototype.$request" in html
    assert "window.df" in html
    # data calls route through the existing /apaas/backend runtime proxy
    assert "/apaas/backend" in html
    # vue-cli mount point preserved
    assert 'id="app"' in html
    assert "<%= " in html  # keeps vue-cli htmlWebpackPlugin template tokens

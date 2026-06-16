import builtins
import importlib
import sys


def test_browser_service_imports_without_playwright(monkeypatch):
    """playwright 被排除/未安装时, 模块顶层 import 不应失败 (PyInstaller exclude 前提)。"""
    # 卸掉已加载的目标模块与 playwright, 强制重新 import
    for name in list(sys.modules):
        if name == "app.coding.browser_service" or name.startswith("playwright"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright" or name.startswith("playwright."):
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # 顶层 import 必须成功(惰性化之后)
    mod = importlib.import_module("app.coding.browser_service")
    assert mod is not None

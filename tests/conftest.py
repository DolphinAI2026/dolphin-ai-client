"""pytest conftest — 全局测试初始化。

必须在所有 test 模块 import 之前把 DATABASE_URL 指向 SQLite in-memory，
否则后续 `import app.database` 会读取 .env 里的 MySQL URL 并尝试真实连接。
conftest.py 由 pytest 在收集测试之前自动加载，因此可以安全地覆盖环境变量。
"""
import os
import sys

# ── 0. 必须第一个运行：强制 SQLite，否则 app.database 引入 MySQL 引擎 ──────
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

# ── 1. 让所有测试都能 import app.* ───────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

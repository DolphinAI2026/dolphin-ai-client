"""Shared pytest config — set Settings env-vars before app.config loads."""
from __future__ import annotations
import os

# 必须在任何 `from app.X` 之前设置 — pydantic-settings 在 Settings class 解析时读取。
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APAAS_ENCRYPTION_KEY", "x" * 32)

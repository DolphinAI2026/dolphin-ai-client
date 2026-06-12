"""AI Builder 使用平台共享模型配置 —— 回归测试。

LLM 配置已改为平台级共享，Builder 允许任一租户会话解析平台默认模型。
"""
import pytest

from app.ai_chat.agent import _resolve_llm_config
from app.crypto import encrypt_password
from app.models import LLMConfig
from app.models.tenant import Tenant
from app.models.ai_chat import AIChatSession


def _cfg(tenant_id, base):
    return LLMConfig(
        tenant_id=tenant_id, config_name="m", provider="dolphin",
        base_url=base, api_key_enc=encrypt_password("k"), model="gpt-5.5",
        purpose="all", is_default=True, status="active",
    )


@pytest.mark.asyncio
async def test_builder_uses_platform_shared_model(db_session):
    t_a = Tenant(tenant_name="A", tenant_code="ta")
    t_b = Tenant(tenant_name="B", tenant_code="tb")
    db_session.add_all([t_a, t_b])
    await db_session.flush()

    # 只有租户 B 配了模型;租户 A 一个都没有
    db_session.add(_cfg(t_b.id, "https://tenant-b/v1"))
    await db_session.flush()

    sess_a = AIChatSession(tenant_id=t_a.id, user_id=1, title="x", selected_llm_config_id=None)
    db_session.add(sess_a)
    await db_session.flush()

    # LLM 配置是平台共享，租户 A 可以使用平台默认模型。
    snap = await _resolve_llm_config(db_session, sess_a)
    assert "tenant-b" in snap.base_url

    # 后创建的默认配置会成为新的平台默认。
    db_session.add(_cfg(t_a.id, "https://tenant-a/v1"))
    await db_session.flush()
    snap = await _resolve_llm_config(db_session, sess_a)
    assert "tenant-a" in snap.base_url, f"应解析最新平台默认模型,得到 {snap.base_url}"

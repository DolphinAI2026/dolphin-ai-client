"""AI Builder 不再跨租户借模型 —— 回归 + 隔离测试

发现:某租户(如售前POC)0 个模型配置时,Builder 的 _resolve_llm_config 原来会**跨租户**
借「任意租户的 is_default / 任意 active」模型 —— 既是产品上要去掉的兜底模型,又是租户隔离泄漏
(等于拿别租户的 API Key 跑当前租户对话)。

修复:只认**当前租户**的配置(selected + tenant default),没有就抛错提示去平台管理添加。
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
async def test_builder_does_not_borrow_other_tenant_model(db_session):
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

    # 不该借租户 B 的模型 → 报错提示去平台管理(隔离 + 无兜底)
    with pytest.raises(RuntimeError, match="平台管理"):
        await _resolve_llm_config(db_session, sess_a)

    # 给租户 A 自己配上 → 正常解析它自己的
    db_session.add(_cfg(t_a.id, "https://tenant-a/v1"))
    await db_session.flush()
    snap = await _resolve_llm_config(db_session, sess_a)
    assert "tenant-a" in snap.base_url, f"应解析当前租户自己的模型,得到 {snap.base_url}"

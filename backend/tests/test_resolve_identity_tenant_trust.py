"""锁住 unified ai-chat 串租户 bug 的修复（_resolve_identity 信任反转）。

背景 bug：用户登录租户 dragonboat，在 unified AI 对话里调 list_platform_envs，
却拿到别的租户(Erick)的环境。根因：mcp_server._resolve_identity 无条件用进程内
current_app slot 的租户**覆盖**掉调用方传入的正确 tenant_id，只在 slot miss 才采
信传入值。unified/admin 等进程内可信入口已把 JWT 派生的真实身份传到这里，却被一个
可能残留/默认租户的 slot 顶掉。

修复：进程内可信入口用 trusted_identity(tenant_id, user_id) 上下文标记可信身份，
_resolve_identity 见到标记就直接采信传入值、不查 slot；外部 /api/mcp/mcp 路径不设
标记，保持原 slot 恢复行为（外部 Dolphin 客户端硬编码 tenant_id=1，仍靠 slot 反查，
不允许凭传入 tenant_id 跨租户）。
"""
from __future__ import annotations

from app.mcp_server import _resolve_identity, trusted_identity
from app.routes.current_app import set_current_app, clear_current_app

DRAGONBOAT_TID = 42   # 用户当前登录的正确租户
WRONG_TID = 99        # slot 里残留/默认的错误租户（对应 bug 里的 Erick）
UID = 7               # 本地 user id


def test_trusted_call_uses_passed_tenant_not_stale_slot():
    """可信进程内调用：即使 slot 残留别的租户，也采信传入的 dragonboat 租户。"""
    clear_current_app(UID)
    # slot 残留错误租户（登录 prime 默认租户 / 切租户没刷新 等场景）
    set_current_app(UID, WRONG_TID, 0, "")
    try:
        with trusted_identity(DRAGONBOAT_TID, UID):
            tid, uid = _resolve_identity(DRAGONBOAT_TID, UID)
        assert tid == DRAGONBOAT_TID, f"可信路径应采信传入租户，得到 {tid}"
        assert uid == UID
    finally:
        clear_current_app(UID)


def test_untrusted_call_still_recovers_from_slot():
    """外部不可信路径（无 trusted 标记）：保持原 slot 恢复行为，不因传入 tenant_id 跨租户。

    外部 Dolphin 客户端硬编码传 tenant_id=1，靠 slot 反查真实租户——这条不能被改坏。
    """
    clear_current_app(UID)
    set_current_app(UID, WRONG_TID, 0, "")
    try:
        # 没有 trusted_identity 标记：模拟外部 HTTP 调用方传了个 tenant_id，
        # 但身份必须以 slot 为准（slot=WRONG_TID）。
        tid, uid = _resolve_identity(DRAGONBOAT_TID, UID)
        assert tid == WRONG_TID, f"外部不可信路径应以 slot 为准，得到 {tid}"
        assert uid == UID
    finally:
        clear_current_app(UID)


def test_trusted_identity_resets_after_context():
    """trusted_identity 退出后必须复位，避免跨请求/跨调用污染（多租户并发安全）。"""
    clear_current_app(UID)
    set_current_app(UID, WRONG_TID, 0, "")
    try:
        with trusted_identity(DRAGONBOAT_TID, UID):
            pass
        # 退出 with 后，标记已复位 → 回到 slot 恢复行为
        tid, _uid = _resolve_identity(DRAGONBOAT_TID, UID)
        assert tid == WRONG_TID, "trusted_identity 退出后标记未复位，串了租户"
    finally:
        clear_current_app(UID)

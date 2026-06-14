"""特征测试 (characterization tests) — workspace/会话绑定解析收口

锁住 workspace_access.py 中收口的 resolve_conversation_app_id 函数的当前行为。
本测试先绿(验证现状),再收口改动也保持绿。

覆盖点:
- 从 Conversation ORM 对象安全读取 coding_app_id(int/str/None/边界)
- 各调用场景的优先级顺序(通过集成逻辑文档化)

【注意】本模块不测试以下(语义各异、刻意保留原地):
- pipeline.py 的绑定持久化状态机(见 test_coding_app_binding_persistence.py)
- tools.py 的 _resolve_local_app_id 多源优先级链(见 test_coding_app_context_tools.py)
- read_query.py 的 _load_bound_application 多候选+DB验证(见 test_coding_bound_app_grounding.py)
- routes/coding.py 的批量自愈回填(见 test_dev_workspace_listing.py)
"""
from __future__ import annotations

from types import SimpleNamespace

from app.coding.workspace_access import resolve_conversation_app_id


# ---------------------------------------------------------------------------
# 纯函数 resolve_conversation_app_id 的行为特征测试
# ---------------------------------------------------------------------------

class _FakeConv:
    """最小 Conversation-like 对象。"""
    def __init__(self, coding_app_id):
        self.coding_app_id = coding_app_id


def test_resolve_conv_app_id_returns_int_when_set():
    """coding_app_id 已设为整数 → 原样返回。"""
    conv = _FakeConv(coding_app_id=42)
    assert resolve_conversation_app_id(conv) == 42


def test_resolve_conv_app_id_returns_none_when_not_set():
    """coding_app_id=None → 返回 None。"""
    conv = _FakeConv(coding_app_id=None)
    assert resolve_conversation_app_id(conv) is None


def test_resolve_conv_app_id_coerces_string_int():
    """coding_app_id='7'(字符串整数,存量数据可能出现) → 返回 int(7)。"""
    conv = _FakeConv(coding_app_id="7")
    assert resolve_conversation_app_id(conv) == 7


def test_resolve_conv_app_id_returns_none_for_empty_string():
    """coding_app_id=''(空串) → 返回 None。"""
    conv = _FakeConv(coding_app_id="")
    assert resolve_conversation_app_id(conv) is None


def test_resolve_conv_app_id_returns_none_for_non_numeric_string():
    """coding_app_id='abc'(不能转 int) → 返回 None。"""
    conv = _FakeConv(coding_app_id="abc")
    assert resolve_conversation_app_id(conv) is None


def test_resolve_conv_app_id_missing_attribute():
    """对象没有 coding_app_id 属性(旧对象兼容) → 返回 None,不抛异常。"""
    conv = SimpleNamespace()  # 没有 coding_app_id 属性
    assert resolve_conversation_app_id(conv) is None


def test_resolve_conv_app_id_none_object():
    """conv=None(查 DB 没找到会话) → 返回 None,不抛异常。"""
    assert resolve_conversation_app_id(None) is None


def test_resolve_conv_app_id_zero_passthrough():
    """coding_app_id=0 → 返回 0(与旧 _coerce_int/_safe_int 逐字等价的特征行为)。

    【现状行为】旧 `int(getattr(...))` 对 0 返回 0,本函数保持等价。
    本原语不对 0 特判;下游(_resolve_local_app_id / _load_bound_application)用
    `is not None` 判断,故 0 会被当作 app_id 去查 DB(通常查不到)。0 视同未绑定的
    降级是行为变化,留作单独任务(见函数 docstring TODO)。
    """
    conv = _FakeConv(coding_app_id=0)
    assert resolve_conversation_app_id(conv) == 0


def test_resolve_conv_app_id_positive_non_zero():
    """正常情况:id=1 → 1。"""
    conv = _FakeConv(coding_app_id=1)
    assert resolve_conversation_app_id(conv) == 1


# ---------------------------------------------------------------------------
# 文档化:各调用场景的优先级顺序(非执行测试,注释为文档)
# ---------------------------------------------------------------------------
#
# 【Point A】tools.py _resolve_local_app_id 优先级链:
#   1. args.local_app_id
#   2. args.app_id
#   3. ctx.extra.local_app_id
#   4. ctx.extra.bound_local_app_id
#   5. ctx.extra.coding_app_id
#   6. ctx.input.local_app_id
#   7. ctx.input.app_context.local_app_id
#   8. Conversation.coding_app_id  ← 调用 resolve_conversation_app_id
#   9. bound_apaas_app_id 反查 Application
#   语义:「装回应用」目标 app;含 DB 查询;保留原地(语义独特)。
#
# 【Point B】read_query.py _load_bound_application 候选链:
#   1. args.app_id
#   2. params.app_id
#   3. Conversation.coding_app_id  ← 调用 resolve_conversation_app_id
#   4. workspace.project_id
#   语义:读应用上下文时确定是哪个 Application;返回 Application 对象;保留原地(语义独特)。
#
# 【Point C】pipeline.py 绑定持久化状态机:
#   写入:params.app_id → Conversation.coding_app_id(首轮建会话/续轮更新)
#   回读:若本轮没带 app_id 但会话已有 → params.app_id = str(conv.coding_app_id)
#   语义:写操作 + 状态机管理;保留原地(不是纯解析)。
#
# 【Point D】pipeline.py _create_workspace_now 优先级:
#   project_id or _param_app_id_int or conv.coding_app_id
#   语义:workspace 创建时的 project_id;强耦合局部变量;保留原地。
#
# 【Point E】routes/coding.py 批量自愈回填:
#   批量 DB 查 Conversation.coding_app_id 补 workspace.project_id
#   语义:列表页优化;批量操作;保留原地(完全不同操作语义)。

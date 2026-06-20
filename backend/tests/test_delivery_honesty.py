"""交付诚实声明 —— 出轮 done 前对照原始请求,显式说明收窄/未起预览,
不再把多端系统静默压成单页 mock 还报完成。修复竞品分析里的 overclaim/静默收窄。"""
from app.coding.delivery_honesty import build_delivery_honesty_note


def test_empty_for_simple_single_request_running():
    # 单一明确请求 + 没要求跑 → 无声明
    assert build_delivery_honesty_note("帮我做一个职位列表表单页", serve_running=False) == ""


def test_scope_note_fires_on_two_ends():
    note = build_delivery_honesty_note("做招聘系统,要管理端和用户端两端", serve_running=True)
    assert note  # 非空
    assert "单一" in note or "未拆分" in note
    assert "管理端" in note or "多端" in note


def test_scope_note_fires_on_admin_plus_user_side():
    # 同时出现管理侧 + 用户侧词 = 强信号
    note = build_delivery_honesty_note("HR 在后台管理职位,求职者在前台投递", serve_running=True)
    assert "单一" in note or "未拆分" in note


def test_scope_note_not_fire_on_single_admin_only():
    # 只提"管理"不构成两端 → 不误拦
    assert build_delivery_honesty_note("做一个职位管理的列表页", serve_running=True) == ""


def test_preview_note_fires_when_asked_to_run_but_no_serve():
    note = build_delivery_honesty_note("做个职位页,要能跑能预览", serve_running=False)
    assert "预览" in note


def test_preview_note_not_fire_when_not_asked_to_run():
    assert build_delivery_honesty_note("做个职位详情组件", serve_running=False) == ""


def test_preview_note_not_fire_when_serve_running():
    assert build_delivery_honesty_note("做个职位页,要能预览", serve_running=True) == ""


def test_both_notes_combine_with_header():
    note = build_delivery_honesty_note(
        "做完整招聘系统,管理端+用户端两端,要能跑能预览", serve_running=False
    )
    assert note.count("- ") >= 2  # 两条
    assert "交付说明" in note

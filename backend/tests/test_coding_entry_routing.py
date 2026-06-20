from app.coding.pipeline import should_decompose


def test_decompose_only_first_turn_strong_signal():
    assert should_decompose("做招聘系统 管理端+用户端两端", is_iteration=False) is True
    assert should_decompose("做招聘系统 管理端+用户端两端", is_iteration=True) is False   # 迭代不分解
    assert should_decompose("做一个职位列表页", is_iteration=False) is False              # 单页不分解
    assert should_decompose("HR 后台管理, 求职者前台投递", is_iteration=False) is True     # 双侧强信号

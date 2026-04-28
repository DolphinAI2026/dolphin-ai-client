"""第一道门校验器测试（Phase B Task 3）"""
from datetime import datetime, timezone

from app.builder_spec.schema import (
    Spec, Phase, Goal, Role, ObjectSpec, FieldSpec, DictSpec, DictOption,
    PermissionSpec, PermissionRule, Completeness, derive_completeness,
)
from app.proposal.validation import (
    CheckResult, ValidationReport, validate,
    check_completeness, check_consistency, check_naming, check_markdown,
)


def _base_spec(*, with_goal=True, with_objects=True, with_roles=True) -> Spec:
    """构造一个 minimal 但合法的 Spec。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    spec = Spec(
        id="spec_test",
        application_id=1,
        version=1,
        phase=Phase.DRAFTING,
        goal=Goal(title="测试应用", summary="s", business_problem="b", confirmed=True) if with_goal else None,
        roles=[Role(code="admin", name="管理员", scope="ALL", confirmed=True)] if with_roles else [],
        objects=[
            ObjectSpec(
                code="t_order",
                name="订单",
                fields=[
                    FieldSpec(code="amount", name="金额", type="数字", confirmed=True),
                ],
                confirmed=True,
            )
        ] if with_objects else [],
        dicts=[],
        permissions=[],
        completeness=Completeness(),
        created_at=now,
        updated_at=now,
        created_by=1,
    )
    spec.completeness = derive_completeness(spec)
    return spec


def test_completeness_passes_full_spec():
    spec = _base_spec()
    result = check_completeness(spec)
    assert result.ok is True
    assert result.issues == []


def test_completeness_fails_missing_goal():
    spec = _base_spec(with_goal=False)
    result = check_completeness(spec)
    assert result.ok is False
    assert any("goal" in i for i in result.issues)


def test_consistency_role_refs_existing_object():
    """字段 ref_model 指向不存在的对象 → consistency 失败"""
    spec = _base_spec()
    # 新增字段引用不存在的对象
    spec.objects[0].fields.append(
        FieldSpec(code="customer_id", name="客户", type="关联",
                  ref_model="t_customer_does_not_exist", confirmed=True)
    )
    result = check_consistency(spec)
    assert result.ok is False
    assert any("t_customer_does_not_exist" in i for i in result.issues)

    # permission 引用不存在的 object
    spec2 = _base_spec()
    spec2.permissions.append(
        PermissionSpec(
            object_code="t_nonexistent",
            rules=[PermissionRule(role="admin", op="view", data="ALL")],
            confirmed=True,
        )
    )
    result2 = check_consistency(spec2)
    assert result2.ok is False
    assert any("t_nonexistent" in i for i in result2.issues)


def test_naming_no_duplicate_object_codes():
    spec = _base_spec()
    # 加一个同 code 的 object
    spec.objects.append(ObjectSpec(code="t_order", name="另一个订单", fields=[], confirmed=True))
    result = check_naming(spec)
    assert result.ok is False
    assert any("t_order" in i for i in result.issues)

    # 同对象内字段 code 重复
    spec2 = _base_spec()
    spec2.objects[0].fields.append(
        FieldSpec(code="amount", name="另一金额", type="数字", confirmed=True)
    )
    result2 = check_naming(spec2)
    assert result2.ok is False
    assert any("amount" in i for i in result2.issues)


def test_validate_aggregates_to_top_level_ok():
    """全过 → top-level ok=True；任一失败 → ok=False"""
    full_spec = _base_spec()
    report = validate(full_spec)
    assert isinstance(report, ValidationReport)
    assert report.ok is True
    assert report.completeness.ok is True
    assert report.consistency.ok is True
    assert report.naming.ok is True
    assert report.markdown.ok is True

    # 把 to_dict 也校验一下
    d = report.to_dict()
    assert d["ok"] is True
    assert "completeness" in d and "issues" in d["completeness"]

    # 任一失败 → 顶层失败
    bad_spec = _base_spec(with_goal=False)
    bad_report = validate(bad_spec)
    assert bad_report.ok is False
    assert bad_report.completeness.ok is False

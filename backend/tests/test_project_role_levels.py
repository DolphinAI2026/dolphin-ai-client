import pytest
from app.project_access import (
    PROJECT_ROLE_LEVELS,
    normalize_project_role,
    project_role_at_least,
    project_role_permissions,
)


def test_role_levels_ordering():
    assert PROJECT_ROLE_LEVELS["viewer"] < PROJECT_ROLE_LEVELS["contributor"]
    assert PROJECT_ROLE_LEVELS["contributor"] < PROJECT_ROLE_LEVELS["maintainer"]
    assert PROJECT_ROLE_LEVELS["maintainer"] < PROJECT_ROLE_LEVELS["owner"]


def test_normalize_legacy_role_names_mapped():
    """旧 'admin' / 'member' 应自动映射到新名称"""
    assert normalize_project_role("admin") == "maintainer"
    assert normalize_project_role("member") == "contributor"
    assert normalize_project_role("owner") == "owner"
    # 完全未知的值降级到最低 'viewer'
    assert normalize_project_role("foo") == "viewer"
    assert normalize_project_role(None) == "viewer"


def test_role_at_least_with_new_names():
    assert project_role_at_least("owner", "maintainer") is True
    assert project_role_at_least("contributor", "maintainer") is False
    assert project_role_at_least("viewer", "contributor") is False
    assert project_role_at_least("contributor", "viewer") is True


def test_role_at_least_with_legacy_names():
    """legacy admin should still satisfy maintainer requirement"""
    assert project_role_at_least("admin", "maintainer") is True
    assert project_role_at_least("member", "contributor") is True


def test_permissions_viewer_read_only():
    perms = project_role_permissions("viewer")
    assert perms["can_view"] is True
    assert perms["can_edit"] is False
    assert perms["can_manage_members"] is False


def test_permissions_contributor_can_edit():
    perms = project_role_permissions("contributor")
    assert perms["can_edit"] is True
    assert perms["can_manage_members"] is False


def test_permissions_maintainer_can_manage_members():
    perms = project_role_permissions("maintainer")
    assert perms["can_edit"] is True
    assert perms["can_manage_members"] is True
    assert perms["can_delete"] is False


def test_permissions_owner_full():
    perms = project_role_permissions("owner")
    assert all(perms.values())

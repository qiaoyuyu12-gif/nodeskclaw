"""AdminAction enum 校验测试。"""

import pytest

from app.models.admin_action import AdminAction


def test_all_actions_use_domain_dot_verb_format():
    """枚举值必须为 domain.verb 字符串格式。"""
    for action in AdminAction:
        assert "." in action.value, f"{action.name} 值缺少域分隔符: {action.value}"


def test_known_admin_actions_present():
    """关键超管动作必须存在（防误删）。"""
    expected = {
        "org.create", "org.update", "org.delete",
        "org_member.add", "org_member.update", "org_member.remove",
        "user.update", "user.reset_password", "user.delete",
        "feature_override.set", "feature_override.clear",
        "auth.login_success", "auth.login_failed", "auth.logout",
    }
    values = {a.value for a in AdminAction}
    missing = expected - values
    assert not missing, f"缺少枚举值: {missing}"


def test_enum_is_str():
    """AdminAction 必须继承 str，用于直接序列化为审计行的 action 列。"""
    assert isinstance(AdminAction.ORG_CREATE, str)
    assert AdminAction.ORG_CREATE == "org.create"

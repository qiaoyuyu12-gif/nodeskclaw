"""超管审计动作枚举 — 所有审计写入必须走 enum，禁止裸字符串。"""

from enum import Enum


class AdminAction(str, Enum):
    """domain.verb 风格的审计动作值。

    新增枚举值时必须同步：
      1. 本 enum
      2. 前端 i18n（zh-CN + en）的 `admin.audit.actions.<value>`
      3. 审计单测（覆盖 service 路径）
    """

    # 组织
    ORG_CREATE = "org.create"
    ORG_UPDATE = "org.update"
    ORG_DELETE = "org.delete"
    # 组织成员
    ORG_MEMBER_ADD = "org_member.add"
    ORG_MEMBER_UPDATE = "org_member.update"
    ORG_MEMBER_REMOVE = "org_member.remove"
    # 用户
    USER_UPDATE = "user.update"
    USER_RESET_PASSWORD = "user.reset_password"
    USER_DELETE = "user.delete"
    # Feature override
    FEATURE_OVERRIDE_SET = "feature_override.set"
    FEATURE_OVERRIDE_CLEAR = "feature_override.clear"
    # 安全（最低审计）
    AUTH_LOGIN_SUCCESS = "auth.login_success"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_LOGOUT = "auth.logout"

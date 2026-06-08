"""Auth-related schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class EmailLoginRequest(BaseModel):
    email: EmailStr
    password: str


class SmsSendRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 8:
            raise ValueError("手机号格式不正确")
        return v


class SmsLoginRequest(BaseModel):
    phone: str
    code: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # seconds


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class OAuthConnectionInfo(BaseModel):
    provider: str
    provider_user_id: str

    model_config = {"from_attributes": True}


class RbacContext(BaseModel):
    """RBAC 上下文（参考 docs/rfcs/0001-rbac-phase1.md §10）。

    第一期纯增量返回，前端可暂不消费；字段就绪后第二期动态菜单 / 按钮权限可直接读。
    """

    # 该用户被授予的全部角色 key（去重 + 字母序）
    role_keys: list[str] = []
    # 该用户全部 perms 集合（去重 + 字母序），格式 module:resource:action
    perms: list[str] = []
    # 该用户可访问的应用入口列表（去重 + 字母序）
    app_codes: list[str] = []


class UserInfo(BaseModel):
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    role: str
    is_active: bool = True
    is_super_admin: bool = False
    has_password: bool = False
    must_change_password: bool = False
    current_org_id: str | None = None
    org_role: str | None = None
    portal_org_role: str | None = None
    last_login_at: datetime | None = None
    oauth_connections: list[OAuthConnectionInfo] = []
    # 第一期 RBAC 增量字段：前端可读但暂不强制使用
    rbac: RbacContext | None = None

    model_config = {"from_attributes": True}


class AccountLoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class VerificationCodeSendRequest(BaseModel):
    account: str = Field(min_length=1, max_length=200)


class VerificationCodeLoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=4, max_length=10)


class ChangePasswordRequest(BaseModel):
    old_password: str | None = Field(default=None, max_length=200)
    new_password: str = Field(min_length=6, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 86400
    user: UserInfo
    needs_org_setup: bool = False
    provider: str | None = None


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    email: EmailStr
    phone: str | None = None
    password: str = Field(min_length=6, max_length=200)


class RegisterResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 86400
    user: UserInfo
    needs_org_setup: bool = False
    provider: str | None = None

"""Organization Model Provider -- admin-managed API keys for LLM providers."""

from sqlalchemy import Boolean, BigInteger, ForeignKey, Index, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class OrgModelProvider(BaseModel):
    __tablename__ = "org_llm_keys"
    __table_args__ = (
        Index(
            "uq_org_llm_keys_org_provider",
            "org_id", "provider",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    org_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    system_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    skip_ssl_verify: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    allowed_models: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    # 是否为平台托管 Key：true=平台超管下发，组织端只读 api_key/base_url 等敏感字段；false=组织 BYOK 自带 Key
    is_platform_managed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )


OrgLlmKey = OrgModelProvider

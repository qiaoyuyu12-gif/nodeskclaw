"""add_skill_manifest

新增 skill_definitions.manifest 列（JSON），用于存储文件夹上传时
将 Python 脚本、assets、reference 内联序列化后的 JSON 内容，
供 agent 直接读取命中。

Revision ID: 5c9e8f1a2b3d
Revises: 4b8e9f0a1b2c
Create Date: 2026-05-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# 当前迁移 ID
revision: str = "5c9e8f1a2b3d"
# 上一个迁移（add_skill_package_fields）
down_revision: Union[str, Sequence[str], None] = "4b8e9f0a1b2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 新增 manifest 列：存放文件夹上传序列化后的完整 JSON
    op.add_column(
        "skill_definitions",
        sa.Column("manifest", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("skill_definitions", "manifest")

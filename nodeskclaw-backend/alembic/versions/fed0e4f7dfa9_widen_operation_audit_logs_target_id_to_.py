"""widen_operation_audit_logs_target_id_to_128

operation_audit_logs.target_id 从 VARCHAR(36) 扩展到 VARCHAR(128)，
以支持复合格式 ID，如 "{org_id}:{feature_id}"（最长约 101 字符）。

Revision ID: fed0e4f7dfa9
Revises: 205b103775c4
Create Date: 2026-05-27 08:32:18.639674

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fed0e4f7dfa9'
down_revision: Union[str, Sequence[str], None] = '205b103775c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将 operation_audit_logs.target_id 从 VARCHAR(36) 扩展到 VARCHAR(128)。"""
    op.alter_column(
        'operation_audit_logs',
        'target_id',
        existing_type=sa.VARCHAR(length=36),
        type_=sa.String(length=128),
        existing_nullable=False,
    )


def downgrade() -> None:
    """回滚：将 operation_audit_logs.target_id 缩回 VARCHAR(36)。"""
    op.alter_column(
        'operation_audit_logs',
        'target_id',
        existing_type=sa.String(length=128),
        type_=sa.VARCHAR(length=36),
        existing_nullable=False,
    )

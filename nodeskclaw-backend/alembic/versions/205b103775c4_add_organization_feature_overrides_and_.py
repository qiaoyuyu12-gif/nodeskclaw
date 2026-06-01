"""add organization_feature_overrides and users.deleted_by

Revision ID: 205b103775c4
Revises: 5c9e8f1a2b3d
Create Date: 2026-05-26 17:14:27.125948

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '205b103775c4'
down_revision: Union[str, Sequence[str], None] = '5c9e8f1a2b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：新增 organization_feature_overrides 表 + users.deleted_by 字段。"""
    # 创建 organization_feature_overrides 表
    # 用于超管对特定组织的 Feature 进行覆盖（强制启用或关闭）
    op.create_table(
        'organization_feature_overrides',
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('feature_id', sa.String(length=64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('set_by_user_id', sa.String(length=36), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['set_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    # 标准索引：deleted_at（软删过滤）、feature_id、org_id
    op.create_index(op.f('ix_organization_feature_overrides_deleted_at'), 'organization_feature_overrides', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_organization_feature_overrides_feature_id'), 'organization_feature_overrides', ['feature_id'], unique=False)
    op.create_index(op.f('ix_organization_feature_overrides_org_id'), 'organization_feature_overrides', ['org_id'], unique=False)
    # Partial Unique Index：仅对未删除记录保唯一，允许软删后重建覆盖记录
    op.create_index('uq_org_feature_overrides_org_feature', 'organization_feature_overrides', ['org_id', 'feature_id'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))

    # 在 users 表新增 deleted_by 字段
    # 记录执行软删操作的超管 user_id，仅 users 表特有
    op.add_column('users', sa.Column('deleted_by', sa.String(length=36), nullable=True))
    # 为 deleted_by 添加自引用 FK，指向 users.id（自引用可空，软删时填充）
    op.create_foreign_key(
        'fk_users_deleted_by_users',
        'users', 'users',
        ['deleted_by'], ['id'],
    )


def downgrade() -> None:
    """降级：回滚 organization_feature_overrides 表 + users.deleted_by 字段。"""
    # 回滚 users.deleted_by（先删 FK 约束，再删列）
    op.drop_constraint('fk_users_deleted_by_users', 'users', type_='foreignkey')
    op.drop_column('users', 'deleted_by')

    # 回滚 organization_feature_overrides 表（先删索引再删表）
    op.drop_index('uq_org_feature_overrides_org_feature', table_name='organization_feature_overrides', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index(op.f('ix_organization_feature_overrides_org_id'), table_name='organization_feature_overrides')
    op.drop_index(op.f('ix_organization_feature_overrides_feature_id'), table_name='organization_feature_overrides')
    op.drop_index(op.f('ix_organization_feature_overrides_deleted_at'), table_name='organization_feature_overrides')
    op.drop_table('organization_feature_overrides')

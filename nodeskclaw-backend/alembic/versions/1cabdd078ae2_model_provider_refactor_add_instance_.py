"""model_provider_refactor_add_instance_provider_configs

Revision ID: 1cabdd078ae2
Revises: effcea6592fc
Create Date: 2026-04-05 05:55:06.264243

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '1cabdd078ae2'
down_revision: Union[str, Sequence[str], None] = 'effcea6592fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # --- Step 1: org_llm_keys.label -> nullable ---
    op.alter_column('org_llm_keys', 'label',
                    existing_type=sa.VARCHAR(length=128),
                    nullable=True)

    # --- Step 2: Dedup org_llm_keys (keep earliest is_active=True per org+provider) ---
    conn = op.get_bind()
    conn.execute(sa.text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY org_id, provider
                       ORDER BY
                           (is_active IS TRUE) DESC,
                           created_at ASC
                   ) AS rn
            FROM org_llm_keys
            WHERE deleted_at IS NULL
        )
        UPDATE org_llm_keys
        SET deleted_at = NOW()
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
    """))

    # --- Step 3: Add partial unique index on org_llm_keys ---
    op.create_index('uq_org_llm_keys_org_provider', 'org_llm_keys',
                    ['org_id', 'provider'], unique=True,
                    postgresql_where=sa.text('deleted_at IS NULL'))

    # --- Step 4: Create instance_provider_configs table ---
    op.create_table('instance_provider_configs',
        sa.Column('instance_id', sa.String(length=36), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('key_source', sa.String(length=16), server_default='org', nullable=False),
        sa.Column('selected_models', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('base_url', sa.String(length=512), nullable=True),
        sa.Column('api_type', sa.String(length=32), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['instance_id'], ['instances.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_instance_provider_configs_deleted_at'),
                    'instance_provider_configs', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_instance_provider_configs_instance_id'),
                    'instance_provider_configs', ['instance_id'], unique=False)
    op.create_index('uq_instance_provider_configs_inst_provider',
                    'instance_provider_configs', ['instance_id', 'provider'],
                    unique=True,
                    postgresql_where=sa.text('deleted_at IS NULL'))

    # --- Step 5: Migrate user_llm_configs -> instance_provider_configs ---
    # For each UserLlmConfig, find matching instances and create records
    conn.execute(sa.text("""
        INSERT INTO instance_provider_configs
            (id, instance_id, provider, key_source, selected_models, created_at, updated_at)
        SELECT
            gen_random_uuid()::text,
            i.id,
            ulc.provider,
            ulc.key_source,
            ulc.selected_models,
            NOW(),
            NOW()
        FROM user_llm_configs ulc
        JOIN instances i
            ON i.created_by = ulc.user_id
            AND i.org_id = ulc.org_id
            AND i.deleted_at IS NULL
        WHERE ulc.deleted_at IS NULL
            AND i.llm_providers::jsonb ? ulc.provider
    """))

    # --- Step 6: Merge instance_llm_overrides into instance_provider_configs ---
    # Update existing records first
    conn.execute(sa.text("""
        UPDATE instance_provider_configs ipc
        SET base_url = ilo.base_url,
            api_type = ilo.api_type,
            updated_at = NOW()
        FROM instance_llm_overrides ilo
        WHERE ilo.instance_id = ipc.instance_id
            AND ilo.provider = ipc.provider
            AND ilo.deleted_at IS NULL
            AND ipc.deleted_at IS NULL
            AND (ilo.base_url IS NOT NULL OR ilo.api_type IS NOT NULL)
    """))

    # Insert records for overrides with no matching instance_provider_config
    conn.execute(sa.text("""
        INSERT INTO instance_provider_configs
            (id, instance_id, provider, key_source, base_url, api_type, created_at, updated_at)
        SELECT
            gen_random_uuid()::text,
            ilo.instance_id,
            ilo.provider,
            'org',
            ilo.base_url,
            ilo.api_type,
            NOW(),
            NOW()
        FROM instance_llm_overrides ilo
        WHERE ilo.deleted_at IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM instance_provider_configs ipc
                WHERE ipc.instance_id = ilo.instance_id
                    AND ipc.provider = ilo.provider
                    AND ipc.deleted_at IS NULL
            )
    """))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_org_llm_keys_org_provider', table_name='org_llm_keys',
                  postgresql_where=sa.text('deleted_at IS NULL'))
    op.alter_column('org_llm_keys', 'label',
                    existing_type=sa.VARCHAR(length=128),
                    nullable=False)
    op.drop_index('uq_instance_provider_configs_inst_provider',
                  table_name='instance_provider_configs',
                  postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index(op.f('ix_instance_provider_configs_instance_id'),
                  table_name='instance_provider_configs')
    op.drop_index(op.f('ix_instance_provider_configs_deleted_at'),
                  table_name='instance_provider_configs')
    op.drop_table('instance_provider_configs')

"""refactor cluster provider_config

Revision ID: 90f0cc94a2c1
Revises: 1e923c533402
Create Date: 2026-03-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = '90f0cc94a2c1'
down_revision: Union[str, Sequence[str], None] = '1e923c533402'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clusters', sa.Column(
        'provider_config', JSONB, server_default='{}', nullable=False,
    ))
    op.add_column('clusters', sa.Column(
        'credentials_encrypted', sa.Text, nullable=True,
    ))

    op.execute("""
        UPDATE clusters SET
            credentials_encrypted = kubeconfig_encrypted,
            provider_config = jsonb_build_object(
                'cloud_vendor', provider,
                'auth_type', auth_type,
                'api_server_url', COALESCE(api_server_url, ''),
                'k8s_version', k8s_version,
                'ingress_class', ingress_class,
                'token_expires_at', token_expires_at::text
            )
        WHERE compute_provider = 'k8s'
    """)

    op.execute("""
        UPDATE clusters SET
            credentials_encrypted = NULL,
            provider_config = '{}'::jsonb
        WHERE compute_provider = 'docker'
    """)

    op.execute("ALTER TABLE clusters ALTER COLUMN kubeconfig_encrypted SET DEFAULT ''")
    op.execute("ALTER TABLE clusters ALTER COLUMN auth_type SET DEFAULT 'unknown'")
    op.execute("ALTER TABLE clusters ALTER COLUMN ingress_class SET DEFAULT 'nginx'")
    op.execute("ALTER TABLE clusters ALTER COLUMN provider SET DEFAULT 'unknown'")


def downgrade() -> None:
    op.execute("""
        UPDATE clusters SET
            kubeconfig_encrypted = COALESCE(credentials_encrypted, ''),
            auth_type = COALESCE(provider_config->>'auth_type', 'unknown'),
            api_server_url = provider_config->>'api_server_url',
            k8s_version = provider_config->>'k8s_version',
            ingress_class = COALESCE(provider_config->>'ingress_class', 'nginx'),
            provider = COALESCE(provider_config->>'cloud_vendor', 'unknown')
        WHERE credentials_encrypted IS NOT NULL OR provider_config != '{}'::jsonb
    """)
    op.execute("ALTER TABLE clusters ALTER COLUMN kubeconfig_encrypted DROP DEFAULT")
    op.execute("ALTER TABLE clusters ALTER COLUMN auth_type DROP DEFAULT")
    op.execute("ALTER TABLE clusters ALTER COLUMN ingress_class DROP DEFAULT")
    op.execute("ALTER TABLE clusters ALTER COLUMN provider DROP DEFAULT")
    op.drop_column('clusters', 'credentials_encrypted')
    op.drop_column('clusters', 'provider_config')

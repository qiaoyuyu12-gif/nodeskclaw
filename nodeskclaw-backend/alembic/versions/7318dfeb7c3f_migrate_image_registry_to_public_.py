"""migrate_image_registry_to_public_namespace

Revision ID: 7318dfeb7c3f
Revises: 90f0cc94a2c1
Create Date: 2026-03-18 15:37:27.267484

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7318dfeb7c3f'
down_revision: Union[str, Sequence[str], None] = '90f0cc94a2c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_OPENCLAW_REGISTRY = "nodesk-center-cn-beijing.cr.volces.com/base-image/nodeskclaw-openclaw-base"
NEW_OPENCLAW_REGISTRY = "nodesk-center-cn-beijing.cr.volces.com/public/deskclaw-openclaw"
NEW_ZEROCLAW_REGISTRY = "nodesk-center-cn-beijing.cr.volces.com/public/deskclaw-zeroclaw"
NEW_NANOBOT_REGISTRY = "nodesk-center-cn-beijing.cr.volces.com/public/deskclaw-nanobot"


def upgrade() -> None:
    conn = op.get_bind()
    sc = sa.table(
        "system_configs",
        sa.column("id", sa.String),
        sa.column("key", sa.String),
        sa.column("value", sa.String),
    )

    conn.execute(
        sa.update(sc)
        .where(sc.c.key == "image_registry")
        .where(sc.c.value == OLD_OPENCLAW_REGISTRY)
        .values(value=NEW_OPENCLAW_REGISTRY)
    )

    for key, value in [
        ("image_registry", NEW_OPENCLAW_REGISTRY),
        ("image_registry_zeroclaw", NEW_ZEROCLAW_REGISTRY),
        ("image_registry_nanobot", NEW_NANOBOT_REGISTRY),
    ]:
        exists = conn.execute(
            sa.select(sa.literal(1)).select_from(sc).where(sc.c.key == key)
        ).scalar()
        if not exists:
            conn.execute(sa.insert(sc).values(
                id=str(uuid.uuid4()), key=key, value=value,
            ))


def downgrade() -> None:
    conn = op.get_bind()
    sc = sa.table(
        "system_configs",
        sa.column("key", sa.String),
        sa.column("value", sa.String),
    )

    conn.execute(
        sa.update(sc)
        .where(sc.c.key == "image_registry")
        .where(sc.c.value == NEW_OPENCLAW_REGISTRY)
        .values(value=OLD_OPENCLAW_REGISTRY)
    )

    conn.execute(sa.delete(sc).where(sc.c.key == "image_registry_zeroclaw"))
    conn.execute(sa.delete(sc).where(sc.c.key == "image_registry_nanobot"))

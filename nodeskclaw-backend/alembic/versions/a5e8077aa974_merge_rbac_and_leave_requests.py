"""merge rbac_phase1 and leave_requests heads

合并两个并行分支：
- ec27348942b6 (add_org_leave_requests)
- 4efa541f362f (rbac_phase1_mom_style)

Revision ID: a5e8077aa974
Revises: ec27348942b6, 4efa541f362f
Create Date: 2026-06-08

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'a5e8077aa974'
down_revision: Union[str, Sequence[str], None] = ('ec27348942b6', '4efa541f362f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

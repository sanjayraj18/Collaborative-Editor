"""changes in the refreshtoken and the document table

Revision ID: b4bd06b80678
Revises: bb112b9c1b63
Create Date: 2026-09-03 18:01:19.884696

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4bd06b80678'
down_revision: Union[str, Sequence[str], None] = 'bb112b9c1b63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('visibility', sa.String(length=16), server_default='private', nullable=False))
    op.add_column('documents', sa.Column('permissions_version', sa.Integer(), server_default='1', nullable=False))

    # Autogenerate does not emit CheckConstraints declared in __table_args__.
    op.create_check_constraint(
        'ck_documents_visibility', 'documents', "visibility in ('private', 'link')"
    )

    # Existing rows need a family_id before the NOT NULL can hold. gen_random_uuid()
    # gives each row its own, which is exactly right: every live session becomes
    # its own chain rather than all of them sharing one revocable family.
    op.add_column(
        'refresh_tokens',
        sa.Column('family_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    )
    # Then drop the default. From here the application must supply family_id
    # explicitly — otherwise a rotation that forgot to carry the family forward
    # would silently get a fresh one, and reuse detection would never fire.
    op.alter_column('refresh_tokens', 'family_id', server_default=None)

    op.add_column('refresh_tokens', sa.Column('used_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_column('refresh_tokens', 'used_at')
    op.drop_column('refresh_tokens', 'family_id')
    op.drop_constraint('ck_documents_visibility', 'documents', type_='check')
    op.drop_column('documents', 'permissions_version')
    op.drop_column('documents', 'visibility')
"""eval run details (Phase 11)

eval_runs: source, lecture_id, n_items, error
eval_items: item_key, kind, refusal_reason, top_score, latency_ms, status

Revision ID: b7e1c4a2f9d3
Revises: d606c7f9f1a1
Create Date: 2026-11-09 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7e1c4a2f9d3'
down_revision: Union[str, Sequence[str], None] = 'd606c7f9f1a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. batch_alter_table so the same migration also runs on SQLite (tests)."""
    with op.batch_alter_table('eval_runs') as batch:
        batch.add_column(sa.Column('source', sa.String(length=32), server_default='harness', nullable=False))
        batch.add_column(sa.Column('lecture_id', sa.Uuid(), nullable=True))
        batch.add_column(sa.Column('n_items', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('error', sa.Text(), nullable=True))
        batch.create_foreign_key(op.f('fk_eval_runs_lecture_id_lectures'), 'lectures', ['lecture_id'], ['id'],
                                 ondelete='SET NULL')
    with op.batch_alter_table('eval_items') as batch:
        batch.add_column(sa.Column('item_key', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('kind', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('refusal_reason', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('top_score', sa.Float(), nullable=True))
        batch.add_column(sa.Column('latency_ms', sa.Float(), nullable=True))
        batch.add_column(sa.Column('status', sa.String(length=32), server_default='ok', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('eval_items') as batch:
        for col in ('status', 'latency_ms', 'top_score', 'refusal_reason', 'kind', 'item_key'):
            batch.drop_column(col)
    with op.batch_alter_table('eval_runs') as batch:
        batch.drop_constraint(op.f('fk_eval_runs_lecture_id_lectures'), type_='foreignkey')
        for col in ('error', 'n_items', 'lecture_id', 'source'):
            batch.drop_column(col)

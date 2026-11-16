"""Store optional AI-prepared text and summaries alongside source extraction."""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_pages", sa.Column("ai_prepared_text", sa.Text(), nullable=True))
    op.add_column("document_pages", sa.Column("ai_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_pages", "ai_summary")
    op.drop_column("document_pages", "ai_prepared_text")

"""store uploaded PDF bytes in the database

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("pdf_data", sa.LargeBinary(), nullable=True))
    with op.batch_alter_table("documents") as batch_op:
        batch_op.alter_column("file_path", existing_type=sa.String(length=512), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.alter_column("file_path", existing_type=sa.String(length=512), nullable=False)
        batch_op.drop_column("pdf_data")

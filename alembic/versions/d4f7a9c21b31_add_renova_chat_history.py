"""add Renova conversational chat history

Revision ID: d4f7a9c21b31
Revises: 7f3c1a9e42d1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4f7a9c21b31"
down_revision: Union[str, None] = "7f3c1a9e42d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "renova_chat_conversations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("context_case_id", sa.Uuid(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["context_case_id"], ["renova_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_renova_chat_conversations_org_user_last",
        "renova_chat_conversations",
        ["organization_id", "user_id", "last_message_at"],
    )
    op.create_table(
        "renova_chat_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("intent", sa.String(), nullable=True),
        sa.Column("referenced_case_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["renova_chat_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["referenced_case_id"], ["renova_cases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_renova_chat_messages_conversation_sequence"),
    )
    op.create_index(
        "ix_renova_chat_messages_conversation_created",
        "renova_chat_messages",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_renova_chat_messages_conversation_created", table_name="renova_chat_messages")
    op.drop_table("renova_chat_messages")
    op.drop_index("ix_renova_chat_conversations_org_user_last", table_name="renova_chat_conversations")
    op.drop_table("renova_chat_conversations")

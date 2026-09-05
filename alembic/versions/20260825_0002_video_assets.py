"""저장 영상 메타데이터 테이블 생성."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_0002"
down_revision: str | None = "20260824_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("robot_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("local_path", sa.String(length=512), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["robot_id"], ["robots.robot_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("robot_id"),
    )
    op.create_index("ix_videos_version", "videos", ["version"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_videos_version", table_name="videos")
    op.drop_table("videos")

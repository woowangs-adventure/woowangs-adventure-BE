"""로봇 상태와 고정 SLAM 지도 메타데이터 테이블 생성."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "robots",
        sa.Column("robot_id", sa.String(length=64), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pose_x", sa.Float(), nullable=True),
        sa.Column("pose_y", sa.Float(), nullable=True),
        sa.Column("pose_yaw", sa.Float(), nullable=True),
        sa.Column("pose_frame_id", sa.String(length=64), nullable=True),
        sa.Column("pose_map_version", sa.String(length=64), nullable=True),
        sa.Column("pose_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column(
            "localization_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "localization_method",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("map_version", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("robot_id"),
    )
    op.create_table(
        "maps",
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("robot_id", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("resolution", sa.Float(), nullable=False),
        sa.Column("origin_x", sa.Float(), nullable=False),
        sa.Column("origin_y", sa.Float(), nullable=False),
        sa.Column("origin_yaw", sa.Float(), nullable=False, server_default="0"),
        sa.Column("frame_id", sa.String(length=64), nullable=False, server_default="map"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_path", sa.String(length=512), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["robot_id"], ["robots.robot_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("version"),
    )
    op.create_index("ix_maps_robot_id", "maps", ["robot_id"], unique=False)
    op.create_index(
        "ix_maps_robot_current",
        "maps",
        ["robot_id", "is_current"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_maps_robot_current", table_name="maps")
    op.drop_index("ix_maps_robot_id", table_name="maps")
    op.drop_table("maps")
    op.drop_table("robots")

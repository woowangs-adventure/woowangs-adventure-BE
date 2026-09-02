from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RobotRecord(Base):
    __tablename__ = "robots"

    robot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pose_x: Mapped[float | None] = mapped_column(Float)
    pose_y: Mapped[float | None] = mapped_column(Float)
    pose_yaw: Mapped[float | None] = mapped_column(Float)
    pose_frame_id: Mapped[str | None] = mapped_column(String(64))
    pose_map_version: Mapped[str | None] = mapped_column(String(64))
    pose_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    localization_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    localization_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unknown",
    )
    map_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MapRecord(Base):
    __tablename__ = "maps"
    __table_args__ = (
        Index("ix_maps_robot_current", "robot_id", "is_current"),
    )

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    robot_id: Mapped[str] = mapped_column(
        ForeignKey("robots.robot_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution: Mapped[float] = mapped_column(Float, nullable=False)
    origin_x: Mapped[float] = mapped_column(Float, nullable=False)
    origin_y: Mapped[float] = mapped_column(Float, nullable=False)
    origin_yaw: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    frame_id: Mapped[str] = mapped_column(String(64), nullable=False, default="map")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class VideoRecord(Base):
    __tablename__ = "videos"

    robot_id: Mapped[str] = mapped_column(
        ForeignKey("robots.robot_id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Pose2D(BaseModel):
    x: float
    y: float
    yaw: float
    frame_id: str = "map"
    timestamp: datetime = Field(default_factory=utc_now)


class MapMetadataInput(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    resolution: float = Field(gt=0)
    origin_x: float
    origin_y: float
    origin_yaw: float = 0.0
    frame_id: str = "map"
    timestamp: datetime = Field(default_factory=utc_now)


class MapState(MapMetadataInput):
    version: str
    image_url: str


class EdgeMessage(BaseModel):
    type: Literal["hello", "heartbeat", "pose", "status"]
    data: dict[str, Any] = Field(default_factory=dict)


class RobotState(BaseModel):
    robot_id: str
    online: bool = False
    last_seen: datetime | None = None
    pose: Pose2D | None = None
    map: MapState | None = None
    status: dict[str, Any] = Field(default_factory=dict)


class RobotListResponse(BaseModel):
    robots: list[RobotState]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]

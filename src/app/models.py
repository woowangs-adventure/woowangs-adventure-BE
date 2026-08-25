from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Pose2D(BaseModel):
    x: float
    y: float
    yaw: float
    frame_id: str = "map"
    map_version: str | None = None
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


class RobotStatus(BaseModel):
    model_config = ConfigDict(extra="allow")

    ros_connected: bool = False
    map_available: bool = False
    tf_available: bool = False
    map_frame: str = "map"
    base_frame: str = "base_footprint"
    localization_available: bool = False
    localization_method: Literal["amcl", "slam_toolbox", "unknown", "none"] = "unknown"
    map_version: str | None = None
    edge: dict[str, Any] | None = None


class RobotState(BaseModel):
    robot_id: str
    online: bool = False
    last_seen: datetime | None = None
    pose: Pose2D | None = None
    map: MapState | None = None
    status: RobotStatus = Field(default_factory=RobotStatus)


class RobotListResponse(BaseModel):
    robots: list[RobotState]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]

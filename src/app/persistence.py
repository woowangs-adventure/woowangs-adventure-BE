import logging
from pathlib import Path
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from .database import DatabaseConnection
from .models import MapState, Pose2D, RobotState, RobotStatus, VideoState, utc_now
from .orm import MapRecord, RobotRecord, VideoRecord

logger = logging.getLogger(__name__)


class StatePersistence(Protocol):
    async def load_states(self) -> list[RobotState]: ...

    async def save_robot(self, state: RobotState) -> None: ...

    async def save_map(self, robot_id: str, state: MapState, local_path: Path) -> None: ...

    async def save_video(self, state: VideoState, local_path: Path) -> None: ...


class NullPersistence:
    async def load_states(self) -> list[RobotState]:
        return []

    async def save_robot(self, state: RobotState) -> None:
        return None

    async def save_map(self, robot_id: str, state: MapState, local_path: Path) -> None:
        return None

    async def save_video(self, state: VideoState, local_path: Path) -> None:
        return None


class SqlAlchemyPersistence:
    def __init__(self, database: DatabaseConnection, api_prefix: str) -> None:
        self._database = database
        self._api_prefix = api_prefix

    async def load_states(self) -> list[RobotState]:
        try:
            async with self._database.session() as session:
                robots = (await session.scalars(select(RobotRecord))).all()
                maps = (
                    await session.scalars(select(MapRecord).where(MapRecord.is_current.is_(True)))
                ).all()
        except (OSError, SQLAlchemyError) as exc:
            logger.warning("Could not restore robot state from PostgreSQL: %s", exc)
            return []

        maps_by_robot = {record.robot_id: self._map_state(record) for record in maps}
        states: list[RobotState] = []
        for record in robots:
            pose = None
            if record.pose_x is not None and record.pose_y is not None and record.pose_yaw is not None:
                pose = Pose2D(
                    x=record.pose_x,
                    y=record.pose_y,
                    yaw=record.pose_yaw,
                    frame_id=record.pose_frame_id or "map",
                    map_version=record.pose_map_version,
                    timestamp=record.pose_timestamp or utc_now(),
                )
            status_data = dict(record.status or {})
            status_data.update({
                "localization_available": record.localization_available,
                "localization_method": record.localization_method,
                "map_version": record.map_version,
            })
            states.append(
                RobotState(
                    robot_id=record.robot_id,
                    online=False,
                    last_seen=record.last_seen,
                    pose=pose,
                    map=maps_by_robot.get(record.robot_id),
                    status=RobotStatus.model_validate(status_data),
                )
            )
        return states

    async def save_robot(self, state: RobotState) -> None:
        try:
            async with self._database.session() as session:
                record = await session.get(RobotRecord, state.robot_id)
                if record is None:
                    record = RobotRecord(robot_id=state.robot_id)
                    session.add(record)
                record.online = state.online
                record.last_seen = state.last_seen
                record.status = state.status.model_dump(mode="json")
                record.localization_available = state.status.localization_available
                record.localization_method = state.status.localization_method
                record.map_version = state.status.map_version
                if state.pose is None:
                    record.pose_x = None
                    record.pose_y = None
                    record.pose_yaw = None
                    record.pose_frame_id = None
                    record.pose_map_version = None
                    record.pose_timestamp = None
                else:
                    record.pose_x = state.pose.x
                    record.pose_y = state.pose.y
                    record.pose_yaw = state.pose.yaw
                    record.pose_frame_id = state.pose.frame_id
                    record.pose_map_version = state.pose.map_version
                    record.pose_timestamp = state.pose.timestamp
                await session.commit()
        except (OSError, SQLAlchemyError) as exc:
            logger.warning("Could not persist robot %s: %s", state.robot_id, exc)

    async def save_map(self, robot_id: str, state: MapState, local_path: Path) -> None:
        try:
            async with self._database.session() as session:
                robot = await session.get(RobotRecord, robot_id)
                if robot is None:
                    robot = RobotRecord(robot_id=robot_id)
                    session.add(robot)
                    await session.flush()
                await session.execute(
                    update(MapRecord)
                    .where(MapRecord.robot_id == robot_id)
                    .values(is_current=False)
                )
                record = await session.get(MapRecord, state.version)
                if record is None:
                    record = MapRecord(version=state.version, robot_id=robot_id)
                    session.add(record)
                record.width = state.width
                record.height = state.height
                record.resolution = state.resolution
                record.origin_x = state.origin_x
                record.origin_y = state.origin_y
                record.origin_yaw = state.origin_yaw
                record.frame_id = state.frame_id
                record.captured_at = state.timestamp
                record.local_path = str(local_path)
                record.is_current = True
                await session.commit()
        except (OSError, SQLAlchemyError) as exc:
            logger.warning("Could not persist map %s for %s: %s", state.version, robot_id, exc)

    async def save_video(self, state: VideoState, local_path: Path) -> None:
        try:
            async with self._database.session() as session:
                robot = await session.get(RobotRecord, state.robot_id)
                if robot is None:
                    robot = RobotRecord(robot_id=state.robot_id)
                    session.add(robot)
                    await session.flush()
                record = await session.get(VideoRecord, state.robot_id)
                if record is None:
                    record = VideoRecord(robot_id=state.robot_id)
                    session.add(record)
                record.version = state.version
                record.content_type = state.content_type
                record.original_filename = state.original_filename
                record.size_bytes = state.size_bytes
                record.local_path = str(local_path)
                record.uploaded_at = state.uploaded_at
                await session.commit()
        except (OSError, SQLAlchemyError) as exc:
            logger.warning("Could not persist video %s for %s: %s", state.version, state.robot_id, exc)

    def _map_state(self, record: MapRecord) -> MapState:
        return MapState(
            width=record.width,
            height=record.height,
            resolution=record.resolution,
            origin_x=record.origin_x,
            origin_y=record.origin_y,
            origin_yaw=record.origin_yaw,
            frame_id=record.frame_id,
            timestamp=record.captured_at,
            version=record.version,
            image_url=(
                f"{self._api_prefix}/robots/{record.robot_id}/map/latest"
                f"?v={record.version}"
            ),
        )

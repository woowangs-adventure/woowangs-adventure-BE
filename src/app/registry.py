import asyncio
from collections import defaultdict
from datetime import timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .models import EdgeMessage, MapState, Pose2D, RobotState, utc_now


class RobotRegistry:
    def __init__(self) -> None:
        self._states: dict[str, RobotState] = {}
        self._dashboards: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    def _state(self, robot_id: str) -> RobotState:
        return self._states.setdefault(robot_id, RobotState(robot_id=robot_id))

    async def list_states(self) -> list[RobotState]:
        async with self._lock:
            return [state.model_copy(deep=True) for state in self._states.values()]

    async def get_state(self, robot_id: str) -> RobotState | None:
        async with self._lock:
            state = self._states.get(robot_id)
            return state.model_copy(deep=True) if state else None

    async def connect_edge(self, robot_id: str) -> None:
        async with self._lock:
            state = self._state(robot_id)
            state.online = True
            state.last_seen = utc_now()
            snapshot = state.model_copy(deep=True)
        await self.broadcast(robot_id, "robot.connection", {
            "online": True,
            "last_seen": snapshot.last_seen.isoformat(),
        })

    async def disconnect_edge(self, robot_id: str) -> None:
        async with self._lock:
            state = self._state(robot_id)
            state.online = False
            state.last_seen = utc_now()
            last_seen = state.last_seen
        await self.broadcast(robot_id, "robot.connection", {
            "online": False,
            "last_seen": last_seen.isoformat(),
        })

    async def handle_edge_message(self, robot_id: str, message: EdgeMessage) -> None:
        now = utc_now()
        event_data: dict[str, Any]
        async with self._lock:
            state = self._state(robot_id)
            state.online = True
            state.last_seen = now
            if message.type == "pose":
                state.pose = Pose2D.model_validate(message.data)
                event_data = state.pose.model_dump(mode="json")
            elif message.type == "status":
                state.status.update(message.data)
                event_data = dict(state.status)
            elif message.type == "hello":
                state.status.update({"edge": message.data})
                event_data = message.data
            else:
                event_data = {"timestamp": now.isoformat()}
        await self.broadcast(robot_id, f"robot.{message.type}", event_data)

    async def update_map(self, robot_id: str, map_state: MapState) -> None:
        async with self._lock:
            state = self._state(robot_id)
            state.map = map_state
            state.last_seen = map_state.timestamp.astimezone(timezone.utc)
        await self.broadcast(robot_id, "map.updated", map_state.model_dump(mode="json"))

    async def add_dashboard(self, robot_id: str, socket: WebSocket) -> RobotState:
        async with self._lock:
            self._dashboards[robot_id].add(socket)
            return self._state(robot_id).model_copy(deep=True)

    async def remove_dashboard(self, robot_id: str, socket: WebSocket) -> None:
        async with self._lock:
            self._dashboards[robot_id].discard(socket)

    async def broadcast(self, robot_id: str, event_type: str, data: dict[str, Any]) -> None:
        async with self._lock:
            sockets = tuple(self._dashboards[robot_id])
        stale: list[WebSocket] = []
        message = {"type": event_type, "robot_id": robot_id, "data": data}
        for socket in sockets:
            try:
                await socket.send_json(message)
            except (RuntimeError, WebSocketDisconnect):
                stale.append(socket)
        if stale:
            async with self._lock:
                for socket in stale:
                    self._dashboards[robot_id].discard(socket)

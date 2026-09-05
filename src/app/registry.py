import asyncio
from collections import defaultdict
from datetime import timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from .models import (
    EdgeControlCommand,
    EdgeMessage,
    MapState,
    Pose2D,
    RobotState,
    RobotStatus,
    utc_now,
)
from .persistence import StatePersistence


class ControlUnavailableError(RuntimeError):
    pass


class RobotRegistry:
    def __init__(self, persistence: StatePersistence) -> None:
        self._persistence = persistence
        self._states: dict[str, RobotState] = {}
        self._dashboards: dict[str, set[WebSocket]] = defaultdict(set)
        self._dashboard_send_locks: dict[WebSocket, asyncio.Lock] = {}
        self._edges: dict[str, WebSocket] = {}
        self._edge_send_locks: dict[str, asyncio.Lock] = {}
        self._controllers: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    def _state(self, robot_id: str) -> RobotState:
        return self._states.setdefault(robot_id, RobotState(robot_id=robot_id))

    async def restore_state(self, restored: RobotState) -> None:
        async with self._lock:
            current = self._state(restored.robot_id)
            restored.online = False
            if current.map is not None and restored.map is None:
                restored.map = current.map
            self._states[restored.robot_id] = restored.model_copy(deep=True)

    async def list_states(self) -> list[RobotState]:
        async with self._lock:
            return [state.model_copy(deep=True) for state in self._states.values()]

    async def get_state(self, robot_id: str) -> RobotState | None:
        async with self._lock:
            state = self._states.get(robot_id)
            return state.model_copy(deep=True) if state else None

    async def connect_edge(self, robot_id: str, socket: WebSocket) -> None:
        async with self._lock:
            self._edges[robot_id] = socket
            self._edge_send_locks[robot_id] = asyncio.Lock()
            state = self._state(robot_id)
            state.online = True
            state.last_seen = utc_now()
            snapshot = state.model_copy(deep=True)
        await self._persistence.save_robot(snapshot)
        await self.broadcast(robot_id, "robot.connection", {
            "online": True,
            "last_seen": snapshot.last_seen.isoformat(),
        })

    async def disconnect_edge(self, robot_id: str, socket: WebSocket) -> None:
        async with self._lock:
            if self._edges.get(robot_id) is not socket:
                return
            self._edges.pop(robot_id, None)
            self._edge_send_locks.pop(robot_id, None)
            self._controllers.pop(robot_id, None)
            state = self._state(robot_id)
            state.online = False
            state.last_seen = utc_now()
            snapshot = state.model_copy(deep=True)
        await self._persistence.save_robot(snapshot)
        await self.broadcast(robot_id, "robot.connection", {
            "online": False,
            "last_seen": snapshot.last_seen.isoformat(),
        })

    async def handle_edge_message(self, robot_id: str, message: EdgeMessage) -> None:
        now = utc_now()
        event_type = f"robot.{message.type}"
        async with self._lock:
            state = self._state(robot_id)
            state.online = True
            state.last_seen = now
            if message.type == "pose":
                state.pose = Pose2D.model_validate(message.data)
                event_data = state.pose.model_dump(mode="json")
            elif message.type == "status":
                merged = state.status.model_dump(mode="python")
                merged.update(message.data)
                state.status = RobotStatus.model_validate(merged)
                event_data = state.status.model_dump(mode="json")
            elif message.type == "hello":
                state.status.edge = dict(message.data)
                event_data = message.data
            elif message.type == "control.ack":
                event_type = "robot.control_ack"
                event_data = message.data
            else:
                event_data = {"timestamp": now.isoformat()}
            snapshot = state.model_copy(deep=True)
        await self._persistence.save_robot(snapshot)
        await self.broadcast(robot_id, event_type, event_data)

    async def update_map(self, robot_id: str, map_state: MapState) -> None:
        async with self._lock:
            state = self._state(robot_id)
            state.map = map_state
            state.last_seen = map_state.timestamp.astimezone(timezone.utc)
            snapshot = state.model_copy(deep=True)
        await self._persistence.save_robot(snapshot)
        await self.broadcast(robot_id, "map.updated", map_state.model_dump(mode="json"))

    async def restore_map(self, robot_id: str, map_state: MapState) -> None:
        async with self._lock:
            self._state(robot_id).map = map_state

    async def add_dashboard(self, robot_id: str, socket: WebSocket) -> RobotState:
        async with self._lock:
            self._dashboards[robot_id].add(socket)
            self._dashboard_send_locks[socket] = asyncio.Lock()
            return self._state(robot_id).model_copy(deep=True)

    async def remove_dashboard(self, robot_id: str, socket: WebSocket) -> None:
        try:
            await self.release_control(robot_id, socket)
        except ControlUnavailableError:
            # 연결이 먼저 끊겼더라도 Edge의 watchdog이 마지막 명령을 만료시킨다.
            pass
        async with self._lock:
            self._dashboards[robot_id].discard(socket)
            self._dashboard_send_locks.pop(socket, None)

    async def acquire_control(self, robot_id: str, socket: WebSocket) -> None:
        async with self._lock:
            if robot_id not in self._edges:
                raise ControlUnavailableError("robot edge agent is offline")
            owner = self._controllers.get(robot_id)
            if owner is not None and owner is not socket:
                raise ControlUnavailableError("another dashboard owns robot control")
            self._controllers[robot_id] = socket

    async def release_control(self, robot_id: str, socket: WebSocket) -> None:
        async with self._lock:
            if self._controllers.get(robot_id) is not socket:
                return
            self._controllers.pop(robot_id, None)
        await self.stop_control(robot_id, socket=None, require_owner=False)

    async def route_velocity(
        self,
        robot_id: str,
        socket: WebSocket,
        *,
        linear: float,
        angular: float,
        ttl_ms: int,
    ) -> EdgeControlCommand:
        async with self._lock:
            if self._controllers.get(robot_id) is not socket:
                raise ControlUnavailableError("control lease is not acquired")
        command = EdgeControlCommand(
            command_id=uuid4().hex,
            linear=linear,
            angular=angular,
            ttl_ms=ttl_ms,
        )
        await self._send_edge(robot_id, "command.velocity", command.model_dump(mode="json"))
        return command

    async def stop_control(
        self,
        robot_id: str,
        socket: WebSocket | None,
        *,
        require_owner: bool = True,
    ) -> EdgeControlCommand:
        if require_owner:
            async with self._lock:
                if self._controllers.get(robot_id) is not socket:
                    raise ControlUnavailableError("control lease is not acquired")
        command = EdgeControlCommand(
            command_id=uuid4().hex,
            linear=0.0,
            angular=0.0,
            ttl_ms=100,
        )
        await self._send_edge(robot_id, "command.stop", command.model_dump(mode="json"))
        return command

    async def send_edge_ack(self, robot_id: str, event: str) -> None:
        await self._send_edge(robot_id, "ack", {"event": event})

    async def send_edge_error(
        self,
        robot_id: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        await self._send_edge(
            robot_id,
            "error",
            {"message": message, "details": details},
        )

    async def _send_edge(self, robot_id: str, event_type: str, data: dict[str, Any]) -> None:
        async with self._lock:
            socket = self._edges.get(robot_id)
            send_lock = self._edge_send_locks.get(robot_id)
        if socket is None or send_lock is None:
            raise ControlUnavailableError("robot edge agent is offline")
        try:
            async with send_lock:
                await socket.send_json({"type": event_type, "robot_id": robot_id, "data": data})
        except (RuntimeError, WebSocketDisconnect) as exc:
            raise ControlUnavailableError("robot edge connection is unavailable") from exc

    async def send_dashboard(
        self,
        socket: WebSocket,
        event_type: str,
        robot_id: str,
        data: dict[str, Any],
    ) -> None:
        async with self._lock:
            send_lock = self._dashboard_send_locks.get(socket)
        if send_lock is None:
            return
        async with send_lock:
            await socket.send_json({"type": event_type, "robot_id": robot_id, "data": data})

    async def broadcast(self, robot_id: str, event_type: str, data: dict[str, Any]) -> None:
        async with self._lock:
            sockets = tuple(self._dashboards[robot_id])
        stale: list[WebSocket] = []
        for socket in sockets:
            try:
                await self.send_dashboard(socket, event_type, robot_id, data)
            except (RuntimeError, WebSocketDisconnect):
                stale.append(socket)
        if stale:
            async with self._lock:
                for socket in stale:
                    self._dashboards[robot_id].discard(socket)
                    self._dashboard_send_locks.pop(socket, None)

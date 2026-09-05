import asyncio
from typing import Literal

from fastapi import WebSocket

WebRtcRole = Literal["publisher", "viewer"]


class WebRtcSignalingHub:
    """한 로봇의 영상 송신자와 단일 대시보드 시청자 사이 신호를 중계한다."""

    def __init__(self) -> None:
        self._peers: dict[str, dict[WebRtcRole, WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, robot_id: str, role: WebRtcRole, socket: WebSocket) -> None:
        previous: WebSocket | None
        other: WebSocket | None
        other_role: WebRtcRole = "viewer" if role == "publisher" else "publisher"
        async with self._lock:
            peers = self._peers.setdefault(robot_id, {})
            previous = peers.get(role)
            peers[role] = socket
            other = peers.get(other_role)

        if previous is not None and previous is not socket:
            await previous.close(code=1012, reason=f"new {role} connected")
        await self._safe_send(
            socket,
            {"type": "webrtc.peer", "robot_id": robot_id, "data": {
                "role": other_role,
                "online": other is not None,
            }},
        )
        if other is not None:
            await self._safe_send(
                other,
                {"type": "webrtc.peer", "robot_id": robot_id, "data": {
                    "role": role,
                    "online": True,
                }},
            )

    async def disconnect(self, robot_id: str, role: WebRtcRole, socket: WebSocket) -> None:
        other: WebSocket | None = None
        other_role: WebRtcRole = "viewer" if role == "publisher" else "publisher"
        async with self._lock:
            peers = self._peers.get(robot_id)
            if peers is None or peers.get(role) is not socket:
                return
            peers.pop(role, None)
            other = peers.get(other_role)
            if not peers:
                self._peers.pop(robot_id, None)
        if other is not None:
            await self._safe_send(
                other,
                {"type": "webrtc.peer", "robot_id": robot_id, "data": {
                    "role": role,
                    "online": False,
                }},
            )

    async def relay(
        self,
        robot_id: str,
        role: WebRtcRole,
        message: dict,
    ) -> None:
        other_role: WebRtcRole = "viewer" if role == "publisher" else "publisher"
        async with self._lock:
            target = self._peers.get(robot_id, {}).get(other_role)
        if target is None:
            return
        await self._safe_send(
            target,
            {"type": message["type"], "robot_id": robot_id, "data": message.get("data", {})},
        )

    @staticmethod
    async def _safe_send(socket: WebSocket, message: dict) -> None:
        try:
            await socket.send_json(message)
        except RuntimeError:
            pass

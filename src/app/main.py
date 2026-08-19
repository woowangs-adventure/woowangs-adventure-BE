import hmac
import re

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .config import Settings, get_settings
from .models import EdgeMessage, HealthResponse, RobotListResponse, RobotState
from .registry import RobotRegistry

ROBOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _token_matches(expected: str, received: str | None) -> bool:
    return bool(received) and hmac.compare_digest(expected, received)


def _valid_robot_id(robot_id: str) -> bool:
    return bool(ROBOT_ID_PATTERN.fullmatch(robot_id))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    registry = RobotRegistry()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings
    app.state.registry = registry
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Content-Type", "X-Device-Token"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(service=settings.app_name, environment=settings.environment)

    @app.get(
        f"{settings.api_prefix}/robots",
        response_model=RobotListResponse,
        tags=["robots"],
    )
    async def list_robots() -> RobotListResponse:
        return RobotListResponse(robots=await registry.list_states())

    @app.get(
        f"{settings.api_prefix}/robots/{{robot_id}}/state",
        response_model=RobotState,
        tags=["robots"],
    )
    async def robot_state(robot_id: str) -> RobotState:
        if not _valid_robot_id(robot_id):
            raise HTTPException(status_code=422, detail="invalid robot id")
        state = await registry.get_state(robot_id)
        if state is None:
            raise HTTPException(status_code=404, detail="robot not found")
        return state

    @app.websocket("/ws/edge/{robot_id}")
    async def edge_socket(websocket: WebSocket, robot_id: str) -> None:
        token = websocket.query_params.get("token") or websocket.headers.get("x-device-token")
        if not _valid_robot_id(robot_id):
            await websocket.close(code=1008, reason="invalid robot id")
            return
        if not _token_matches(settings.edge_device_token, token):
            await websocket.close(code=1008, reason="invalid device token")
            return
        await websocket.accept()
        await registry.connect_edge(robot_id)
        try:
            while True:
                try:
                    message = EdgeMessage.model_validate(await websocket.receive_json())
                except ValidationError as exc:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "invalid edge message", "details": exc.errors()},
                    })
                    continue
                await registry.handle_edge_message(robot_id, message)
                await websocket.send_json({"type": "ack", "data": {"event": message.type}})
        except WebSocketDisconnect:
            pass
        finally:
            await registry.disconnect_edge(robot_id)

    @app.websocket("/ws/dashboard/{robot_id}")
    async def dashboard_socket(websocket: WebSocket, robot_id: str) -> None:
        if not _valid_robot_id(robot_id):
            await websocket.close(code=1008, reason="invalid robot id")
            return
        await websocket.accept()
        snapshot = await registry.add_dashboard(robot_id, websocket)
        await websocket.send_json({
            "type": "state.snapshot",
            "robot_id": robot_id,
            "data": snapshot.model_dump(mode="json"),
        })
        try:
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "robot_id": robot_id,
                        "data": {},
                    })
        except WebSocketDisconnect:
            pass
        finally:
            await registry.remove_dashboard(robot_id, websocket)

    return app


app = create_app()

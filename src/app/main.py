import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .config import Settings, get_settings
from .database import Database, DatabaseConnection
from .map_store import MapStore, validate_robot_id
from .models import (
    ControlCapabilities,
    DashboardMessage,
    EdgeMessage,
    HealthResponse,
    MapMetadataInput,
    MapState,
    ReadinessResponse,
    RobotListResponse,
    RobotState,
    VelocityCommand,
)
from .persistence import NullPersistence, SqlAlchemyPersistence, StatePersistence
from .registry import ControlUnavailableError, RobotRegistry


def _token_matches(expected: str, received: str | None) -> bool:
    return bool(received) and hmac.compare_digest(expected, received)


def create_app(
    settings: Settings | None = None,
    database: DatabaseConnection | None = None,
    persistence: StatePersistence | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    database = database or Database(settings.database_url)
    persistence = persistence or (
        NullPersistence()
        if settings.environment == "test"
        else SqlAlchemyPersistence(database, settings.api_prefix)
    )
    registry = RobotRegistry(persistence)
    map_store = MapStore(settings.data_dir, settings.max_map_bytes)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        map_store.prepare()
        for robot_id, map_state in map_store.load_all_metadata().items():
            await registry.restore_map(robot_id, map_state)
            await persistence.save_map(
                robot_id,
                map_state,
                map_store.latest_path(robot_id),
            )
        for restored in await persistence.load_states():
            await registry.restore_state(restored)
        yield
        await database.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.registry = registry
    app.state.map_store = map_store
    app.state.database = database
    app.state.persistence = persistence
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=False,
        allow_methods=["GET", "PUT", "OPTIONS"],
        allow_headers=["Content-Type", "X-Device-Token"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(service=settings.app_name, environment=settings.environment)

    @app.get("/ready", response_model=ReadinessResponse, tags=["system"])
    async def readiness(response: Response) -> ReadinessResponse:
        database_ready = await database.ping()
        if not database_ready:
            response.status_code = 503
        return ReadinessResponse(
            status="ready" if database_ready else "not_ready",
            database="ok" if database_ready else "unavailable",
        )

    @app.get(
        f"{settings.api_prefix}/control/capabilities",
        response_model=ControlCapabilities,
        tags=["control"],
    )
    async def control_capabilities() -> ControlCapabilities:
        return ControlCapabilities(
            enabled=settings.control_enabled,
            ttl_ms=settings.control_command_ttl_ms,
        )

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
        try:
            validate_robot_id(robot_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        state = await registry.get_state(robot_id)
        if state is None:
            raise HTTPException(status_code=404, detail="robot not found")
        return state

    @app.get(
        f"{settings.api_prefix}/maps/current",
        response_model=MapState,
        tags=["slam"],
    )
    async def current_map() -> MapState:
        state = await registry.get_state(settings.map_source_robot_id)
        if state is None or state.map is None:
            raise HTTPException(status_code=404, detail="current map not found")
        return state.map

    @app.put(
        f"{settings.api_prefix}/robots/{{robot_id}}/map",
        response_model=MapState,
        tags=["slam"],
    )
    async def upload_map(
        robot_id: str,
        metadata: Annotated[str, Form()],
        image: Annotated[UploadFile, File()],
        device_token: Annotated[
            str | None,
            Header(alias="X-Device-Token"),
        ] = None,
    ) -> MapState:
        if not _token_matches(settings.edge_device_token, device_token):
            raise HTTPException(status_code=401, detail="invalid device token")
        try:
            validate_robot_id(robot_id)
            parsed = MapMetadataInput.model_validate(json.loads(metadata))
        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if image.content_type != "image/png":
            raise HTTPException(status_code=415, detail="map image must use image/png")
        content = await image.read(settings.max_map_bytes + 1)
        try:
            map_path = map_store.save_png(robot_id, content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        version = hashlib.sha256(content).hexdigest()
        state = MapState(
            **parsed.model_dump(),
            version=version,
            image_url=f"{settings.api_prefix}/robots/{robot_id}/map/latest?v={version}",
        )
        map_store.save_metadata(robot_id, state)
        await persistence.save_map(robot_id, state, map_path)
        await registry.update_map(robot_id, state)
        return state

    @app.get(
        f"{settings.api_prefix}/robots/{{robot_id}}/map/latest",
        response_class=FileResponse,
        tags=["slam"],
    )
    async def latest_map(robot_id: str) -> FileResponse:
        try:
            path: Path = map_store.latest_path(robot_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not path.exists():
            raise HTTPException(status_code=404, detail="map not found")
        return FileResponse(
            path,
            media_type="image/png",
            filename=f"{robot_id}-latest-map.png",
            headers={"Cache-Control": "no-cache"},
        )

    @app.websocket("/ws/edge/{robot_id}")
    async def edge_socket(websocket: WebSocket, robot_id: str) -> None:
        token = websocket.query_params.get("token") or websocket.headers.get("x-device-token")
        try:
            validate_robot_id(robot_id)
        except ValueError:
            await websocket.close(code=1008, reason="invalid robot id")
            return
        if not _token_matches(settings.edge_device_token, token):
            await websocket.close(code=1008, reason="invalid device token")
            return
        await websocket.accept()
        await registry.connect_edge(robot_id, websocket)
        try:
            while True:
                try:
                    message = EdgeMessage.model_validate(await websocket.receive_json())
                except ValidationError as exc:
                    await registry.send_edge_error(
                        robot_id,
                        "invalid edge message",
                        exc.errors(),
                    )
                    continue
                await registry.handle_edge_message(robot_id, message)
                await registry.send_edge_ack(robot_id, message.type)
        except WebSocketDisconnect:
            pass
        finally:
            await registry.disconnect_edge(robot_id, websocket)

    @app.websocket("/ws/dashboard/{robot_id}")
    async def dashboard_socket(websocket: WebSocket, robot_id: str) -> None:
        try:
            validate_robot_id(robot_id)
        except ValueError:
            await websocket.close(code=1008, reason="invalid robot id")
            return
        await websocket.accept()
        snapshot = await registry.add_dashboard(robot_id, websocket)
        await registry.send_dashboard(
            websocket,
            "state.snapshot",
            robot_id,
            snapshot.model_dump(mode="json"),
        )
        try:
            while True:
                try:
                    message = DashboardMessage.model_validate(await websocket.receive_json())
                    if message.type == "ping":
                        await registry.send_dashboard(websocket, "pong", robot_id, {})
                        continue
                    if not settings.control_enabled:
                        raise ControlUnavailableError("robot control is disabled by server")
                    if message.type == "control.acquire":
                        await registry.acquire_control(robot_id, websocket)
                        await registry.send_dashboard(websocket, "control.acquired", robot_id, {})
                    elif message.type == "control.velocity":
                        command = VelocityCommand.model_validate(message.data)
                        routed = await registry.route_velocity(
                            robot_id,
                            websocket,
                            linear=command.linear,
                            angular=command.angular,
                            ttl_ms=command.ttl_ms,
                        )
                        await registry.send_dashboard(
                            websocket,
                            "control.sent",
                            robot_id,
                            routed.model_dump(mode="json"),
                        )
                    elif message.type == "control.stop":
                        stopped = await registry.stop_control(robot_id, websocket)
                        await registry.send_dashboard(
                            websocket,
                            "control.sent",
                            robot_id,
                            stopped.model_dump(mode="json"),
                        )
                    elif message.type == "control.release":
                        await registry.release_control(robot_id, websocket)
                        await registry.send_dashboard(websocket, "control.released", robot_id, {})
                except (ValidationError, ControlUnavailableError) as exc:
                    details = exc.errors() if isinstance(exc, ValidationError) else None
                    await registry.send_dashboard(websocket, "error", robot_id, {
                        "message": str(exc),
                        "details": details,
                    })
        except WebSocketDisconnect:
            pass
        finally:
            await registry.remove_dashboard(robot_id, websocket)

    return app


app = create_app()

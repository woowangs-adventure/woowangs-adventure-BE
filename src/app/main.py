import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .config import Settings, get_settings
from .map_store import MapStore, validate_robot_id
from .models import (
    EdgeMessage,
    HealthResponse,
    MapMetadataInput,
    MapState,
    RobotListResponse,
    RobotState,
)
from .registry import RobotRegistry


def _token_matches(expected: str, received: str | None) -> bool:
    return bool(received) and hmac.compare_digest(expected, received)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    registry = RobotRegistry()
    map_store = MapStore(settings.data_dir, settings.max_map_bytes)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        map_store.prepare()
        yield

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.registry = registry
    app.state.map_store = map_store
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
            map_store.save_png(robot_id, content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        version = uuid4().hex
        state = MapState(
            **parsed.model_dump(),
            version=version,
            image_url=f"{settings.api_prefix}/robots/{robot_id}/map/latest?v={version}",
        )
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
        try:
            validate_robot_id(robot_id)
        except ValueError:
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
                    await websocket.send_json({"type": "pong", "robot_id": robot_id, "data": {}})
        except WebSocketDisconnect:
            pass
        finally:
            await registry.remove_dashboard(robot_id, websocket)

    return app


app = create_app()

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
    HTTPException,
    Response,
    Security,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from pydantic import ValidationError

from .config import Settings, get_settings
from .database import Database, DatabaseConnection
from .map_store import MapStore, validate_robot_id
from .models import (
    ControlCapabilities,
    DashboardMessage,
    EdgeMessage,
    HealthResponse,
    LightCommand,
    MapMetadataInput,
    MapState,
    ReadinessResponse,
    RobotListResponse,
    RobotState,
    VelocityCommand,
    VideoState,
)
from .persistence import NullPersistence, SqlAlchemyPersistence, StatePersistence
from .registry import ControlUnavailableError, RobotRegistry
from .video_store import VideoStore
from .webrtc import WebRtcRole, WebRtcSignalingHub

OPENAPI_TAGS = [
    {
        "name": "system",
        "description": "서버와 PostgreSQL의 동작 상태를 확인합니다.",
    },
    {
        "name": "robots",
        "description": "등록된 로봇과 실시간 상태를 조회합니다.",
    },
    {
        "name": "slam",
        "description": "저장된 SLAM 지도 이미지와 좌표 메타데이터를 관리합니다.",
    },
    {
        "name": "control",
        "description": "웹 원격 조작 기능의 활성화 여부와 제한값을 조회합니다.",
    },
    {
        "name": "video",
        "description": "미니로봇의 저장 영상을 업로드하고 브라우저에서 재생합니다.",
    },
]

DEVICE_TOKEN_HEADER = APIKeyHeader(
    name="X-Device-Token",
    scheme_name="EdgeDeviceToken",
    description=(
        "백엔드 .env의 WOOWANGS_EDGE_DEVICE_TOKEN 값입니다. "
        "Swagger 우측 상단 Authorize에서 한 번 입력하면 보호된 업로드 API에 재사용됩니다."
    ),
    auto_error=False,
)


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
    video_store = VideoStore(settings.data_dir, settings.max_video_bytes)
    webrtc_hub = WebRtcSignalingHub()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        map_store.prepare()
        video_store.prepare()
        for robot_id, map_state in map_store.load_all_metadata().items():
            await registry.restore_map(robot_id, map_state)
            await persistence.save_map(
                robot_id,
                map_state,
                map_store.latest_path(robot_id),
            )
        for robot_id, video_state in video_store.load_all_metadata().items():
            await persistence.save_video(
                video_state,
                video_store.content_path(robot_id, video_state),
            )
        for restored in await persistence.load_states():
            await registry.restore_state(restored)
        yield
        await database.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "TurtleBot3 SLAM 지도, 로봇 상태, 저장 영상 및 원격 조작 중계를 제공하는 API입니다. "
            "HTTP API는 이 Swagger 화면에서 실행할 수 있습니다. "
            "WebSocket(`/ws/*`)은 OpenAPI 규격에 포함되지 않으므로 별도 클라이언트로 테스트합니다."
        ),
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.registry = registry
    app.state.map_store = map_store
    app.state.video_store = video_store
    app.state.webrtc_hub = webrtc_hub
    app.state.database = database
    app.state.persistence = persistence
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=False,
        allow_methods=["GET", "PUT", "OPTIONS"],
        allow_headers=["Content-Type", "X-Device-Token"],
    )

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["system"],
        summary="서버 상태 확인",
    )
    async def health() -> HealthResponse:
        return HealthResponse(service=settings.app_name, environment=settings.environment)

    @app.get(
        "/ready",
        response_model=ReadinessResponse,
        tags=["system"],
        summary="서버와 데이터베이스 준비 상태 확인",
    )
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
        summary="웹 원격 조작 지원 상태 확인",
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
        summary="전체 로봇 상태 조회",
    )
    async def list_robots() -> RobotListResponse:
        return RobotListResponse(robots=await registry.list_states())

    @app.get(
        f"{settings.api_prefix}/robots/{{robot_id}}/state",
        response_model=RobotState,
        tags=["robots"],
        summary="로봇 상태 조회",
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
        summary="현재 운영 지도 메타데이터 조회",
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
        summary="SLAM 지도 업로드",
        description=(
            "PNG 지도와 JSON 메타데이터를 함께 업로드합니다. "
            "먼저 Swagger 우측 상단 Authorize에 장치 토큰을 입력하세요."
        ),
    )
    async def upload_map(
        robot_id: str,
        metadata: Annotated[str, Form()],
        image: Annotated[UploadFile, File()],
        device_token: Annotated[str | None, Security(DEVICE_TOKEN_HEADER)],
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
        summary="최신 SLAM 지도 이미지 조회",
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

    @app.put(
        f"{settings.api_prefix}/robots/{{robot_id}}/video",
        response_model=VideoState,
        tags=["video"],
        summary="저장 영상 업로드",
        description=(
            "MP4 또는 WebM 파일을 업로드합니다. robot_id에는 MINI-01을 입력하고, "
            "Swagger 우측 상단 Authorize에 장치 토큰을 먼저 입력하세요."
        ),
    )
    async def upload_video(
        robot_id: str,
        video: Annotated[UploadFile, File()],
        device_token: Annotated[str | None, Security(DEVICE_TOKEN_HEADER)],
    ) -> VideoState:
        if not _token_matches(settings.edge_device_token, device_token):
            raise HTTPException(status_code=401, detail="invalid device token")
        try:
            validate_robot_id(robot_id)
            path, size, version = await video_store.save_upload(robot_id, video)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        state = VideoState(
            robot_id=robot_id,
            content_type=video.content_type or "video/mp4",
            original_filename=Path(video.filename or path.name).name,
            size_bytes=size,
            version=version,
            content_url=(
                f"{settings.api_prefix}/robots/{robot_id}/video/content?v={version}"
            ),
        )
        video_store.save_metadata(robot_id, state)
        await persistence.save_video(state, path)
        return state

    @app.get(
        f"{settings.api_prefix}/robots/{{robot_id}}/video",
        response_model=VideoState,
        tags=["video"],
        summary="저장 영상 메타데이터 조회",
    )
    async def video_metadata(robot_id: str) -> VideoState:
        try:
            state = video_store.load_metadata(robot_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if state is None:
            raise HTTPException(status_code=404, detail="video not found")
        return state

    @app.get(
        f"{settings.api_prefix}/robots/{{robot_id}}/video/content",
        response_class=FileResponse,
        tags=["video"],
        summary="저장 영상 재생 또는 다운로드",
    )
    async def video_content(robot_id: str) -> FileResponse:
        try:
            state = video_store.load_metadata(robot_id)
            path = video_store.content_path(robot_id, state) if state is not None else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if state is None or path is None or not path.exists():
            raise HTTPException(status_code=404, detail="video not found")
        return FileResponse(
            path,
            media_type=state.content_type,
            filename=state.original_filename,
            content_disposition_type="inline",
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
                    elif message.type == "control.light":
                        light = LightCommand.model_validate(message.data)
                        routed_light = await registry.route_light(
                            robot_id, websocket, on=light.on,
                        )
                        await registry.send_dashboard(
                            websocket, "control.sent", robot_id,
                            routed_light.model_dump(mode="json"),
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

    @app.websocket("/ws/webrtc/{robot_id}/{role}")
    async def webrtc_signaling(
        websocket: WebSocket,
        robot_id: str,
        role: WebRtcRole,
    ) -> None:
        try:
            validate_robot_id(robot_id)
        except ValueError:
            await websocket.close(code=1008, reason="invalid robot id")
            return
        if role not in ("publisher", "viewer"):
            await websocket.close(code=1008, reason="invalid WebRTC role")
            return
        token = websocket.query_params.get("token") or websocket.headers.get("x-device-token")
        if role == "publisher" and not _token_matches(settings.edge_device_token, token):
            await websocket.close(code=1008, reason="invalid device token")
            return
        await websocket.accept()
        await webrtc_hub.connect(robot_id, role, websocket)
        try:
            while True:
                message = await websocket.receive_json()
                message_type = message.get("type") if isinstance(message, dict) else None
                if message_type == "ping":
                    await websocket.send_json({"type": "pong", "robot_id": robot_id, "data": {}})
                elif message_type in {
                    "webrtc.ready",
                    "webrtc.offer",
                    "webrtc.answer",
                    "webrtc.ice",
                }:
                    await webrtc_hub.relay(robot_id, role, message)
                else:
                    await websocket.send_json({
                        "type": "error",
                        "robot_id": robot_id,
                        "data": {"message": "unsupported WebRTC signaling message"},
                    })
        except WebSocketDisconnect:
            pass
        finally:
            await webrtc_hub.disconnect(robot_id, role, websocket)

    return app


app = create_app()

# Robot Inspection Backend

TurtleBot3의 SLAM 지도와 위치·상태 데이터를 수신하여 웹 대시보드에 제공하는
FastAPI 백엔드입니다. ROS 2와 직접 통신하지 않으며, 로봇과 같은 네트워크에서
실행되는 Edge Agent가 HTTP와 WebSocket으로 데이터를 전송합니다.

## 주요 기능

- 장치 토큰 기반 Edge Agent 인증
- SLAM 지도 PNG 업로드 및 최신 지도 조회
- 지도 메타데이터 로컬 영속화 및 서버 재시작 시 복원
- 로봇 위치, AMCL localization 상태, heartbeat 실시간 수신
- 대시보드 WebSocket 실시간 이벤트 전파
- PostgreSQL ORM 영속화 및 Alembic 스키마 마이그레이션
- 단일 조종자 lease와 만료 시간 기반 로봇 속도 명령 중계
- MP4/WebM 저장 영상 업로드·재생과 WebRTC 시그널링 중계
- Swagger API 문서
- 자동 테스트

## 기술 스택

- Python 3.10+
- FastAPI
- Uvicorn
- Pydantic
- SQLAlchemy AsyncIO
- PostgreSQL 16
- WebSocket
- Pytest

## 구조

```text
TurtleBot3 / ROS 2
        ↓
연결 노트북 Edge Agent
        ↓ HTTP · WebSocket
FastAPI Backend
        ↓ REST · WebSocket
React Dashboard
```

## 환경 설정

`.env.example`을 복사하여 `.env`를 생성합니다.

```bash
cp .env.example .env
```

개발 환경에서는 백엔드와 Edge Agent의 장치 토큰이 같아야 합니다.

```env
WOOWANGS_ENVIRONMENT=development
WOOWANGS_EDGE_DEVICE_TOKEN=replace-with-a-random-device-token
WOOWANGS_MAP_SOURCE_ROBOT_ID=TB3-01
WOOWANGS_CONTROL_ENABLED=false
WOOWANGS_CONTROL_COMMAND_TTL_MS=300
WOOWANGS_DATA_DIR=data
WOOWANGS_MAX_VIDEO_BYTES=524288000
WOOWANGS_FRONTEND_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]

POSTGRES_DB=robot_inspection
POSTGRES_USER=robot_local_dev
POSTGRES_PASSWORD=robot_local_dev_password
POSTGRES_PORT=5432
WOOWANGS_DATABASE_URL=postgresql+asyncpg://robot_local_dev:robot_local_dev_password@127.0.0.1:5432/robot_inspection
```

실제 토큰과 `.env` 파일은 Git에 커밋하지 않습니다.
예시에 포함된 PostgreSQL 비밀번호는 로컬 개발 전용이며 배포 환경에서는 반드시
별도의 안전한 값으로 교체합니다. 데이터베이스 포트는 로컬 호스트에만 공개됩니다.

## PostgreSQL 실행

PostgreSQL을 직접 설치하지 않고 Docker Compose로 실행합니다. Docker Desktop이
실행 중인 상태에서 백엔드 프로젝트 루트에서 다음 명령을 사용합니다.

```bash
docker compose up -d postgres
docker compose ps
```

정상 준비 여부와 연결을 확인합니다.

```bash
docker compose exec postgres pg_isready \
  -U robot_local_dev \
  -d robot_inspection

docker compose exec postgres psql \
  -U robot_local_dev \
  -d robot_inspection \
  -c "SELECT current_database(), current_user;"

python -m alembic upgrade head
python -m alembic current
```

`robots` 테이블에는 최신 pose, localization 상태와 지도 버전을 저장하고, `maps`와
`videos` 테이블에는 지도·영상 메타데이터와 로컬 파일 경로를 저장합니다. 새 환경에서는
FastAPI를 실행하기 전에 반드시 `python -m alembic upgrade head`를 실행합니다.

컨테이너만 중지하거나 다시 실행할 때는 다음 명령을 사용합니다.

```bash
docker compose stop postgres
docker compose start postgres
```

컨테이너를 내려도 `postgres_data` Docker 볼륨에 데이터가 유지됩니다.

```bash
docker compose down
```

`docker compose down -v`는 데이터베이스 볼륨과 모든 데이터를 삭제하므로 초기화가
명확히 필요한 경우에만 사용합니다.

## 실행 방법

### Windows Git Bash

```bash
cd woowangs-adventure-BE

py -3 -m venv .venv
source .venv/Scripts/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

test -f .env || cp .env.example .env
python -m alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

이미 `.env`가 있다면 다시 복사하지 않습니다.

### macOS / Linux

```bash
cd woowangs-adventure-BE

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

test -f .env || cp .env.example .env
python -m alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 지도 저장 위치

지도 PNG는 S3에 업로드하지 않고 백엔드 프로젝트의 로컬 파일 시스템에 저장합니다.

```text
data/maps/<robot_id>/latest.png
data/maps/<robot_id>/metadata.json
```

기본 로봇의 실제 예시는 `data/maps/TB3-01/latest.png`와
`data/maps/TB3-01/metadata.json`입니다. PostgreSQL에는 PNG 바이너리가 아닌 지도
버전(SHA-256), 좌표 메타데이터와 로컬 경로만 저장합니다. 서버를 여러 대로 확장하는
시점에는 공유 볼륨 같은 별도 파일 저장 전략이 필요합니다.

## 카메라 영상

실시간 송신기가 준비되기 전에는 MP4 또는 WebM 파일을 백엔드에 업로드해 대시보드에서
재생할 수 있습니다. 파일은 S3가 아니라 다음 로컬 경로에 저장하고 PostgreSQL에는
메타데이터와 로컬 경로만 저장합니다.

```text
data/videos/<robot_id>/latest.mp4  # 또는 latest.webm
data/videos/<robot_id>/metadata.json
```

미니로봇 저장 영상을 등록하는 예시는 다음과 같습니다.

```bash
curl -X PUT "http://127.0.0.1:8000/api/v1/robots/MINI-01/video" \
  -H "X-Device-Token: replace-with-a-random-device-token" \
  -F "video=@./inspection.mp4;type=video/mp4"
```

`curl` 대신 Swagger에서 테스트할 수도 있습니다.

1. `http://127.0.0.1:8000/docs`에 접속합니다.
2. 우측 상단 `Authorize`를 누르고 `.env`의 `WOOWANGS_EDGE_DEVICE_TOKEN` 값을 입력합니다.
3. `video`의 `PUT /api/v1/robots/{robot_id}/video`에서 `Try it out`을 누릅니다.
4. `robot_id`에 `MINI-01`을 입력하고 파일 선택에서 로컬 MP4 또는 WebM을 고릅니다.
5. `Execute`를 누른 뒤 반환된 `content_url`을 열어 재생을 확인합니다.

프로젝트 루트의 로컬 테스트 영상은 Git에 포함하지 않습니다. 현재 테스트 파일명이
`test_vedio.mp4`라면 그대로 파일 선택 창에서 고르면 됩니다.

프론트엔드의 `VITE_CAMERA_MODE=auto`는 WebRTC 실시간 영상을 우선하고 송신자가 없으면
위 저장 영상을 사용합니다. `/ws/webrtc/<robot_id>/publisher`와 `viewer`는 SDP와 ICE
신호만 중계하며 영상 데이터는 FastAPI를 통과하지 않습니다. 로컬 Wi-Fi 밖의 클라우드
환경에서는 별도 TURN 서버와 HTTPS/WSS 설정이 필요합니다.

## 웹 수동 조작

개발 중 의도치 않은 이동을 막기 위해 기본값은 비활성화입니다. 실기 테스트 때만
`.env`에서 다음 값을 설정하고 백엔드를 재시작합니다.

```env
WOOWANGS_CONTROL_ENABLED=true
WOOWANGS_CONTROL_COMMAND_TTL_MS=300
```

브라우저는 정규화 속도 `-1.0..1.0`을 보내며 실제 최대 속도는 Edge Agent 설정이
제한합니다. 하나의 로봇은 한 대시보드만 조종권을 얻을 수 있고, 키 입력이 갱신되지
않거나 WebSocket이 끊기면 Edge Agent watchdog이 정지 명령을 발행합니다. 미니로봇도
추후 `MINI-01` Edge가 같은 프로토콜을 구현하면 그대로 추가할 수 있습니다.

## 접속 주소

- Health: `http://127.0.0.1:8000/health`
- Readiness: `http://127.0.0.1:8000/ready`
- Swagger: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- 로봇 상태: `http://127.0.0.1:8000/api/v1/robots/TB3-01/state`
- 현재 SLAM 지도 정보: `http://127.0.0.1:8000/api/v1/maps/current`
- 최신 지도: `http://127.0.0.1:8000/api/v1/robots/TB3-01/map/latest`
- 조작 지원 상태: `http://127.0.0.1:8000/api/v1/control/capabilities`
- 미니로봇 저장 영상 정보: `http://127.0.0.1:8000/api/v1/robots/MINI-01/video`

다른 노트북에서 접속할 때는 `127.0.0.1` 대신 백엔드가 실행 중인 노트북의
로컬 IP를 사용합니다.

## 테스트

가상환경을 활성화한 상태에서 실행합니다.

```bash
python -m pytest
python -m ruff check .
```

실제 로봇 없이 WebSocket 위치 수신을 확인하려면 백엔드를 실행한 뒤 별도
터미널에서 다음 명령을 실행합니다.

```bash
python scripts/mock_edge.py --token replace-with-a-random-device-token
```

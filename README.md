# Robot Inspection Backend

TurtleBot3의 SLAM 지도와 위치·상태 데이터를 수신하여 웹 대시보드에 제공하는
FastAPI 백엔드입니다. ROS 2와 직접 통신하지 않으며, 로봇과 같은 네트워크에서
실행되는 Edge Agent가 HTTP와 WebSocket으로 데이터를 전송합니다.

## 주요 기능

- 장치 토큰 기반 Edge Agent 인증
- SLAM 지도 PNG 업로드 및 최신 지도 조회
- 지도 메타데이터 로컬 영속화 및 서버 재시작 시 복원
- 로봇 위치, 상태, heartbeat 실시간 수신
- 대시보드 WebSocket 실시간 이벤트 전파
- PostgreSQL 연결 준비 상태 확인
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
WOOWANGS_DATA_DIR=data
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
```

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
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 접속 주소

- Health: `http://127.0.0.1:8000/health`
- Readiness: `http://127.0.0.1:8000/ready`
- Swagger: `http://127.0.0.1:8000/docs`
- 로봇 상태: `http://127.0.0.1:8000/api/v1/robots/TB3-01/state`
- 현재 SLAM 지도 정보: `http://127.0.0.1:8000/api/v1/maps/current`
- 최신 지도: `http://127.0.0.1:8000/api/v1/robots/TB3-01/map/latest`

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

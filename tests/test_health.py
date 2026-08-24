from fastapi.testclient import TestClient

from app.main import create_app


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Woowangs Adventure Backend",
        "environment": "test",
    }


class AvailableDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class UnavailableDatabase:
    async def ping(self) -> bool:
        return False

    async def close(self) -> None:
        pass


def test_readiness_returns_ok_when_database_is_available(settings):
    with TestClient(create_app(settings, database=AvailableDatabase())) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_readiness_returns_503_when_database_is_unavailable(settings):
    with TestClient(create_app(settings, database=UnavailableDatabase())) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}

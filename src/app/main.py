from fastapi import FastAPI

from .config import Settings, get_settings
from .models import HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(service=settings.app_name, environment=settings.environment)

    return app


app = create_app()

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the API with validated, replaceable settings."""
    resolved_settings = settings or get_settings()
    configure_logging(api_key=resolved_settings.opendota_api_key)

    application = FastAPI(title="Metadex API", version="0.1.0")
    application.state.settings = resolved_settings

    @application.get("/")
    async def root() -> dict[str, str]:
        """Confirm that the backend scaffold is available."""
        return {"name": "Metadex API", "status": "ready"}

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Expose a minimal, dependency-free health check."""
        return {"status": "ok"}

    return application


app = create_app()

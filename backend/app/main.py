from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.analytics.catalog import HeroCatalogRepository
from app.analytics.heroes import HeroStatsRepository
from app.analytics.recommendations import RecommendationRepository
from app.api.catalog import router as catalog_router
from app.api.errors import register_error_handlers
from app.api.examples import preserve_openapi_examples
from app.api.heroes import router as heroes_router
from app.api.models import HealthResponse
from app.api.recommendations import router as recommendations_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.storage.hero_catalog import DuckDBHeroCatalogRepository
from app.storage.hero_queries import DuckDBHeroStatsRepository
from app.storage.recommendation_queries import DuckDBRecommendationRepository


def create_app(
    settings: Settings | None = None,
    *,
    hero_repository: HeroStatsRepository | None = None,
    recommendation_repository: RecommendationRepository | None = None,
    hero_catalog_repository: HeroCatalogRepository | None = None,
) -> FastAPI:
    """Create the API with validated, replaceable settings."""
    resolved_settings = settings or get_settings()
    configure_logging(api_key=resolved_settings.opendota_api_key)

    application = FastAPI(title="Metadex API", version="1.0.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["Accept"],
        allow_credentials=False,
    )
    application.state.settings = resolved_settings
    application.state.hero_catalog_repository = (
        hero_catalog_repository
        if hero_catalog_repository is not None
        else DuckDBHeroCatalogRepository(resolved_settings.duckdb_path)
    )
    application.state.hero_repository = (
        hero_repository
        if hero_repository is not None
        else DuckDBHeroStatsRepository(resolved_settings.duckdb_path)
    )
    application.state.recommendation_repository = (
        recommendation_repository
        if recommendation_repository is not None
        else DuckDBRecommendationRepository(resolved_settings.duckdb_path)
    )
    register_error_handlers(application)
    application.include_router(heroes_router)
    application.include_router(catalog_router)
    application.include_router(recommendations_router)
    preserve_openapi_examples(application)

    @application.get("/")
    async def root() -> dict[str, str]:
        """Confirm that the backend scaffold is available."""
        return {"name": "Metadex API", "status": "ready"}

    @application.get("/health", response_model=HealthResponse, tags=["Operations"])
    async def health() -> HealthResponse:
        """Expose a minimal, dependency-free health check."""
        return HealthResponse()

    return application


app = create_app()

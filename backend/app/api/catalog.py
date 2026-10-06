"""Local catalog endpoints; requests never contact OpenDota."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.models import ErrorResponse

router = APIRouter(prefix="/api/v1/catalog", tags=["Catalogs"])


class HeroNameResponse(BaseModel):
    hero_id: int = Field(gt=0)
    name: str


class HeroCatalogResponse(BaseModel):
    version_id: str
    heroes: list[HeroNameResponse]


class ItemNameResponse(BaseModel):
    item_key: str
    name: str


class ItemCatalogResponse(BaseModel):
    version_id: str
    items: list[ItemNameResponse]


@router.get(
    "/heroes",
    response_model=HeroCatalogResponse,
    summary="List hero names from the published OpenDota catalog",
    responses={503: {"model": ErrorResponse, "description": "Publication unavailable."}},
)
def hero_catalog(request: Request) -> dict:
    catalog = request.app.state.hero_catalog_repository.read()
    return {
        "version_id": catalog.version_id,
        "heroes": [
            {"hero_id": hero_id, "name": name} for hero_id, name in sorted(catalog.names.items())
        ],
    }


@router.get(
    "/items",
    response_model=ItemCatalogResponse,
    summary="List item names from the published OpenDota catalog",
    responses={503: {"model": ErrorResponse, "description": "Publication unavailable."}},
)
def item_catalog(request: Request) -> dict:
    catalog = request.app.state.hero_catalog_repository.read()
    return {
        "version_id": catalog.version_id,
        "items": [
            {"item_key": key, "name": name} for key, name in sorted(catalog.item_names.items())
        ],
    }

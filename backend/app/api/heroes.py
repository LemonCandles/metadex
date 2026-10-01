"""Versioned hero endpoints; no collection or storage-specific operations here."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.analytics.heroes import HeroFilters, HeroStatsService
from app.api.examples import DETAIL_EXAMPLE, RANKING_EXAMPLE, TREND_EXAMPLE
from app.api.models import (
    DetailResponse,
    ErrorResponse,
    HeroQuery,
    RankingQuery,
    RankingResponse,
    TrendResponse,
)

router = APIRouter(
    prefix="/api/v1/meta/heroes",
    tags=["Hero metrics"],
    responses={
        422: {"model": ErrorResponse, "description": "Invalid or unsupported parameters."},
        503: {
            "model": ErrorResponse,
            "description": "No publication, unavailable catalog or active writer.",
        },
        500: {"model": ErrorResponse, "description": "Unexpected internal failure."},
    },
)


def get_hero_service(request: Request) -> HeroStatsService:
    settings = request.app.state.settings
    return HeroStatsService(
        request.app.state.hero_repository,
        window_days=settings.meta_window_days,
        min_sample_size=settings.min_sample_size,
    )


def query_filters(query: HeroQuery) -> HeroFilters:
    return HeroFilters(
        cohort=query.cohort,
        game_mode=query.game_mode,
        lobby_type=query.lobby_type,
        skill_min=query.skill_min,
        skill_max=query.skill_max,
        rank_coverage_min=query.rank_coverage_min,
    )


Service = Annotated[HeroStatsService, Depends(get_hero_service)]
HeroId = Annotated[
    int, Path(gt=0, le=2_147_483_647, description="Hero ID observed in the publication.")
]


@router.get(
    "",
    response_model=RankingResponse,
    summary="Rank heroes from published matches",
    description="Rates use eligible matches for picks and hero picks for wins. Default period: "
    "the configured number of complete UTC days before today. Small samples are excluded "
    "unless include_below_min=true. Ties use ascending hero_id. No request collects data.",
    responses={200: {"content": {"application/json": {"example": RANKING_EXAMPLE}}}},
)
def ranking(query: Annotated[RankingQuery, Query()], service: Service) -> dict:
    period = service.period(query.period_start, query.period_end)
    return service.ranking(
        period,
        query_filters(query),
        order_by=query.order_by,
        order=query.order,
        include_below_min=query.include_below_min,
    )


@router.get(
    "/{hero_id}",
    response_model=DetailResponse,
    summary="Inspect a hero, including small samples",
    description="A hero observed in the publication remains inspectable with zero picks in the "
    "requested period. A hero never observed returns 404. Example counts come from the first "
    "two real OpenDota fixtures; publication ID and update time are illustrative.",
    responses={
        404: {"model": ErrorResponse},
        200: {"content": {"application/json": {"example": DETAIL_EXAMPLE}}},
    },
)
def detail(hero_id: HeroId, query: Annotated[HeroQuery, Query()], service: Service) -> dict:
    period = service.period(query.period_start, query.period_end)
    return service.detail(hero_id, period, query_filters(query))


@router.get(
    "/{hero_id}/trend",
    response_model=TrendResponse,
    summary="Inspect daily metrics and a comparable prior window",
    description="Compare equal adjacent windows with identical filters from one publication. "
    "Deltas remain null if either window lacks eligible matches on any day. Days without "
    "matches have null rates. Having data every day does not imply complete source coverage.",
    responses={
        404: {"model": ErrorResponse},
        200: {"content": {"application/json": {"example": TREND_EXAMPLE}}},
    },
)
def trend(hero_id: HeroId, query: Annotated[HeroQuery, Query()], service: Service) -> dict:
    period = service.period(query.period_start, query.period_end)
    return service.trend(hero_id, period, query_filters(query))

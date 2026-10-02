"""Versioned endpoints for draft and item evidence from published local data."""

from dataclasses import fields
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.analytics.recommendations import ItemTiming, RecommendationContext, RecommendationService
from app.api.heroes import query_filters
from app.api.models import ErrorResponse
from app.api.recommendation_models import (
    ItemRecommendationQuery,
    RecommendationQuery,
    RecommendationResponse,
)

router = APIRouter(
    prefix="/api/v1/recommendations",
    tags=["Recommendations"],
    responses={
        422: {"model": ErrorResponse, "description": "Invalid or unsupported parameters."},
        503: {
            "model": ErrorResponse,
            "description": "Data unavailable; reprocess pre-stage-10 "
            "publications to materialize recommendation_stats.",
        },
        500: {"model": ErrorResponse, "description": "Unexpected internal failure."},
    },
)


def get_recommendation_service(request: Request) -> RecommendationService:
    settings = request.app.state.settings
    return RecommendationService(
        request.app.state.recommendation_repository,
        window_days=settings.meta_window_days,
        min_sample_size=settings.min_sample_size,
    )


Service = Annotated[RecommendationService, Depends(get_recommendation_service)]


def query_context(query: RecommendationQuery, hero_id: int | None = None) -> RecommendationContext:
    return RecommendationContext(
        hero_id=hero_id,
        position=query.position,
        ally_ids=tuple(sorted(query.ally_ids)),
        opponent_ids=tuple(sorted(query.opponent_ids)),
    )


@router.get(
    "/heroes",
    response_model=RecommendationResponse,
    summary="Recommend heroes with explicit draft evidence",
    description="All supplied allies and opponents must appear on the specified sides. "
    "Heroes already in the draft are excluded even after fallback. Rank eligible candidates "
    "by win rate descending, sample descending, then hero ID ascending. A single context "
    "is used for the entire ranking. Unknown economic positions are never inferred.",
)
def heroes(query: Annotated[RecommendationQuery, Query()], service: Service) -> dict:
    period = service.period(query.period_start, query.period_end)
    return service.recommend(
        "hero",
        period,
        query_filters(query),
        query_context(query),
        allow_fallback=query.allow_fallback,
        limit=query.limit,
    )


@router.get(
    "/items",
    response_model=RecommendationResponse,
    summary="Recommend recorded first purchases for a hero",
    description="Counts distinct participant-item observations from purchase_log. Final "
    "inventory, recipes and purchases after match end are excluded. Uses first chronological "
    "purchase with source index as tie breaker. Default latest purchase is 1200 seconds. "
    "Duration bounds, purchase time and zero-based source order remain fixed during fallback. "
    "Rank by win rate descending, sample descending, then item key ascending. These are "
    "associations with match outcomes, subject to prior-advantage and survival biases.",
    responses={404: {"model": ErrorResponse}},
)
def items(query: Annotated[ItemRecommendationQuery, Query()], service: Service) -> dict:
    period = service.period(query.period_start, query.period_end)
    timing = ItemTiming(**{field.name: getattr(query, field.name) for field in fields(ItemTiming)})
    return service.recommend(
        "item",
        period,
        query_filters(query),
        query_context(query, query.hero_id),
        allow_fallback=query.allow_fallback,
        limit=query.limit,
        timing=timing,
    )

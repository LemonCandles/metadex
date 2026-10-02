"""Validated draft context and explainable recommendation responses."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.api.models import HeroQuery, MetadataResponse

Identifier = Annotated[int, Field(gt=0, le=2_147_483_647)]


class RecommendationQuery(HeroQuery):
    position: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Economic position 1..5. Unknown positions are never inferred from lane_role. "
        "Returns unsupported_context if the publication has no known positions.",
    )
    ally_ids: list[Identifier] = Field(default_factory=list, max_length=4)
    opponent_ids: list[Identifier] = Field(default_factory=list, max_length=5)
    allow_fallback: bool = Field(
        default=True,
        description="Try exact context, then remove allies, then opponents. "
        "Dates, meta, hero, position and item timing are never removed.",
    )
    limit: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def validate_draft(self) -> Self:
        if len(set(self.ally_ids)) != len(self.ally_ids):
            raise ValueError("ally_ids must be distinct")
        if len(set(self.opponent_ids)) != len(self.opponent_ids):
            raise ValueError("opponent_ids must be distinct")
        if set(self.ally_ids) & set(self.opponent_ids):
            raise ValueError("allies and opponents must not overlap")
        return self


class ItemRecommendationQuery(RecommendationQuery):
    hero_id: Identifier
    duration_min_seconds: int | None = Field(default=None, ge=1, le=2_147_483_647)
    duration_max_seconds: int | None = Field(default=None, ge=1, le=2_147_483_647)
    purchase_time_min_seconds: int | None = Field(
        default=None,
        ge=-2_147_483_648,
        le=2_147_483_647,
    )
    purchase_time_max_seconds: int = Field(
        default=1200,
        ge=-2_147_483_648,
        le=2_147_483_647,
        description="Inclusive latest first purchase. Default 1200s excludes late purchases; "
        "increasing it explicitly includes late-game evidence and its biases.",
    )
    purchase_index_min: int | None = Field(default=None, ge=0, le=2_147_483_647)
    purchase_index_max: int | None = Field(
        default=None,
        ge=0,
        le=2_147_483_647,
        description="Inclusive zero-based index in the original purchase_log, including recipes.",
    )

    @model_validator(mode="after")
    def validate_item_context(self) -> Self:
        if self.hero_id in (*self.ally_ids, *self.opponent_ids):
            raise ValueError("hero_id must not be an ally or opponent")
        for minimum, maximum in (
            (self.duration_min_seconds, self.duration_max_seconds),
            (self.purchase_time_min_seconds, self.purchase_time_max_seconds),
            (self.purchase_index_min, self.purchase_index_max),
        ):
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError("minimum must not exceed maximum")
        return self


class ContextResponse(BaseModel):
    hero_id: int | None
    position: int | None
    ally_ids: list[int]
    opponent_ids: list[int]


class SupportedContextsResponse(BaseModel):
    position: bool
    allies: Literal[True]
    opponents: Literal[True]
    hero: bool


class ItemTimingResponse(BaseModel):
    duration_min_seconds: int | None
    duration_max_seconds: int | None
    purchase_time_min_seconds: int | None
    purchase_time_max_seconds: int
    purchase_index_min: int | None
    purchase_index_max: int | None


class RecommendationOrderingResponse(BaseModel):
    order_by: Literal["win_rate_desc"]
    tie_breakers: list[Literal["sample_size_desc", "hero_id_asc", "item_key_asc"]]


class FallbackAttemptResponse(BaseModel):
    level: Literal["exact", "without_allies", "without_draft"]
    context: ContextResponse
    context_sample_size: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)


class FallbackResponse(BaseModel):
    allowed: bool
    applied: bool
    removed_filters: list[Literal["ally_ids", "opponent_ids"]]
    attempts: list[FallbackAttemptResponse]


class SuggestionResponse(BaseModel):
    hero_id: int = Field(gt=0)
    item_key: str | None
    sample_size: int = Field(ge=1)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate: float = Field(ge=0, le=1)
    meets_min_sample: Literal[True]
    context_sample_size: int = Field(ge=1)
    context: ContextResponse
    explanation: str
    mean_duration_seconds: float = Field(gt=0)
    mean_purchase_time_seconds: float | None
    mean_purchase_index: float | None = Field(ge=0)


class RecommendationResponse(MetadataResponse):
    status: Literal["ok", "no_data", "insufficient_evidence", "unsupported_context"]
    requested_context: ContextResponse
    used_context: ContextResponse
    supported_contexts: SupportedContextsResponse
    item_timing: ItemTimingResponse | None
    ordering: RecommendationOrderingResponse
    fallback: FallbackResponse
    limitations: list[str]
    explanation: str
    recommendations: list[SuggestionResponse]

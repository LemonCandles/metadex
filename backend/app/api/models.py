"""Versioned HTTP inputs and outputs, independent from DuckDB row representations."""

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.heroes import HeroPeriod, Order, OrderBy


class HeroQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cohort: Literal["all", "high_skill_public_v1"] = Field(
        default="all",
        description="Explicit cohort. High skill requires rank >=70, coverage >=5 "
        "and balanced modes/lobbies.",
    )

    period_start: date | None = Field(
        default=None, description="First included UTC day (YYYY-MM-DD)."
    )
    period_end: date | None = Field(
        default=None, description="First excluded UTC day (YYYY-MM-DD)."
    )
    game_mode: int | None = Field(default=None, ge=0, le=2_147_483_647)
    lobby_type: int | None = Field(default=None, ge=0, le=2_147_483_647)
    skill_min: float | None = Field(
        default=None, ge=0, le=85, description="Inclusive lower bound of the reported average rank."
    )
    skill_max: float | None = Field(
        default=None, ge=0, le=85, description="Inclusive upper bound of the reported average rank."
    )
    rank_coverage_min: int | None = Field(
        default=None, ge=1, le=10, description="Minimum number of players contributing rank data."
    )

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("period_start and period_end must be provided together")
        if self.period_start is not None and self.period_end is not None:
            period = HeroPeriod(self.period_start, self.period_end)
            if period.start.toordinal() <= period.days:
                raise ValueError("period is too early to calculate the previous window")
        if (
            self.skill_min is not None
            and self.skill_max is not None
            and self.skill_min > self.skill_max
        ):
            raise ValueError("skill_min must not exceed skill_max")
        return self


class RankingQuery(HeroQuery):
    order_by: OrderBy = "win_rate"
    order: Order = "desc"
    include_below_min: bool = Field(
        default=False,
        description="Include small samples for auditing; eligibility remains visible.",
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class PeriodResponse(BaseModel):
    start: date
    end: date
    timezone: Literal["UTC"]
    end_exclusive: Literal[True]


class FiltersResponse(BaseModel):
    cohort: Literal["all", "high_skill_public_v1"]
    game_mode: int | None
    lobby_type: int | None
    skill_min: float | None
    skill_max: float | None
    rank_coverage_min: int | None


class SampleResponse(BaseModel):
    matches: int = Field(
        ge=0, description="All eligible matches, including those without this hero."
    )
    participants: int = Field(ge=0)
    observed_days: int = Field(ge=0)
    expected_days: int = Field(ge=1, le=365)
    min_sample_size: int = Field(ge=1)


class HeroMetricsResponse(BaseModel):
    hero_id: int = Field(gt=0)
    picks: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    pick_rate: float | None = Field(
        ge=0, le=1, description="Picks / eligible matches; null without matches."
    )
    win_rate: float | None = Field(ge=0, le=1, description="Wins / picks; null without picks.")
    sample_size: int = Field(ge=0, description="Number of hero picks.")
    meets_min_sample: bool


class MetadataResponse(BaseModel):
    period: PeriodResponse
    filters: FiltersResponse
    updated_at: datetime = Field(description="UTC publication time, not the request time.")
    version_id: str
    sample: SampleResponse


class OrderingResponse(BaseModel):
    order_by: OrderBy
    order: Order
    tie_breaker: Literal["hero_id_asc"]


class RankingResponse(MetadataResponse):
    status: Literal["ok", "no_data", "below_min_sample"]
    ordering: OrderingResponse
    include_below_min: bool
    heroes: list[HeroMetricsResponse]


class DetailResponse(MetadataResponse):
    status: Literal["ok", "no_data"]
    hero: HeroMetricsResponse


class TrendPointResponse(HeroMetricsResponse):
    date: date
    matches: int = Field(ge=0)
    has_data: bool


class ComparisonResponse(BaseModel):
    status: Literal[
        "comparable", "insufficient_history", "incomplete_current_period", "no_current_data"
    ]
    period: PeriodResponse
    sample: SampleResponse
    hero: HeroMetricsResponse
    pick_rate_delta: float | None = Field(
        description="Current minus previous rate, in the 0..1 scale."
    )
    win_rate_delta: float | None = Field(
        description="Null unless both windows have comparable data."
    )


class TrendResponse(MetadataResponse):
    hero: HeroMetricsResponse
    points: list[TrendPointResponse]
    comparison: ComparisonResponse


class ErrorDetail(BaseModel):
    location: list[str | int]
    message: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody

"""Storage-independent hero metrics over one consistent published dataset."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, Protocol, Self

from app.core.clock import utc_now

OrderBy = Literal["picks", "wins", "losses", "pick_rate", "win_rate"]
Order = Literal["asc", "desc"]


class RepositoryUnavailable(Exception):
    """The published dataset cannot currently be read."""


class HeroNotFound(Exception):
    """The hero has never appeared in the current publication."""


@dataclass(frozen=True)
class HeroPeriod:
    start: date
    end: date

    def __post_init__(self) -> None:
        if not 1 <= self.days <= 365:
            raise ValueError("period must contain 1..365 days; end is exclusive")

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def previous(self) -> Self:
        return HeroPeriod(self.start - timedelta(days=self.days), self.start)

    def as_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "timezone": "UTC", "end_exclusive": True}


@dataclass(frozen=True)
class HeroFilters:
    cohort: Literal["all", "high_skill_public_v1"] = "all"
    game_mode: int | None = None
    lobby_type: int | None = None
    skill_min: float | None = None
    skill_max: float | None = None
    rank_coverage_min: int | None = None


@dataclass(frozen=True)
class HeroDailyCount:
    day: date
    hero_id: int
    picks: int
    wins: int


@dataclass(frozen=True)
class PublishedHeroData:
    version_id: str
    updated_at: datetime
    match_counts: dict[date, int]
    heroes: tuple[HeroDailyCount, ...]
    hero_exists: bool = True


class HeroStatsRepository(Protocol):
    """Read counts without exposing SQL, files or database connections to callers."""

    def read(
        self,
        period: HeroPeriod,
        filters: HeroFilters,
        *,
        hero_id: int | None = None,
        compare: bool = False,
    ) -> PublishedHeroData: ...


def hero_metrics(hero_id: int, picks: int, wins: int, matches: int, minimum: int) -> dict[str, Any]:
    """Divide accumulated counts, never average already calculated rates."""
    return {
        "hero_id": hero_id,
        "picks": picks,
        "wins": wins,
        "losses": picks - wins,
        "pick_rate": picks / matches if matches else None,
        "win_rate": wins / picks if picks else None,
        "sample_size": picks,
        "meets_min_sample": picks >= minimum,
    }


class HeroStatsService:
    def __init__(
        self, repository: HeroStatsRepository, *, window_days: int, min_sample_size: int
    ) -> None:
        self.repository = repository
        self.window_days = window_days
        self.min_sample_size = min_sample_size

    def period(self, start: date | None, end: date | None) -> HeroPeriod:
        if (start is None) != (end is None):
            raise ValueError("period_start and period_end must be provided together")
        if start is not None and end is not None:
            return HeroPeriod(start, end)
        today = utc_now().date()
        return HeroPeriod(today - timedelta(days=self.window_days), today)

    def _window(
        self, data: PublishedHeroData, period: HeroPeriod, filters: HeroFilters
    ) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
        days = {
            day: count
            for day, count in data.match_counts.items()
            if period.start <= day < period.end
        }
        matches = sum(days.values())
        totals: dict[int, list[int]] = {}
        for row in data.heroes:
            if period.start <= row.day < period.end:
                counts = totals.setdefault(row.hero_id, [0, 0])
                counts[0] += row.picks
                counts[1] += row.wins
        heroes = {
            hero_id: hero_metrics(hero_id, picks, wins, matches, self.min_sample_size)
            for hero_id, (picks, wins) in totals.items()
        }
        metadata = {
            "period": period.as_dict(),
            "filters": asdict(filters),
            "updated_at": data.updated_at,
            "version_id": data.version_id,
            "sample": {
                "matches": matches,
                "participants": matches * 10,
                "observed_days": len(days),
                "expected_days": period.days,
                "min_sample_size": self.min_sample_size,
            },
        }
        return metadata, heroes

    def ranking(
        self,
        period: HeroPeriod,
        filters: HeroFilters,
        *,
        order_by: OrderBy = "win_rate",
        order: Order = "desc",
        include_below_min: bool = False,
    ) -> dict[str, Any]:
        data = self.repository.read(period, filters)
        metadata, heroes = self._window(data, period, filters)
        items = [hero for hero in heroes.values() if include_below_min or hero["meets_min_sample"]]

        def sort_key(hero: dict[str, Any]) -> tuple[bool, float, int]:
            value = hero[order_by]
            number = value if value is not None else 0
            return value is None, -number if order == "desc" else number, hero["hero_id"]

        items.sort(key=sort_key)
        status = "ok" if items else "below_min_sample" if heroes else "no_data"
        return {
            **metadata,
            "status": status,
            "ordering": {"order_by": order_by, "order": order, "tie_breaker": "hero_id_asc"},
            "include_below_min": include_below_min,
            "heroes": items,
        }

    def detail(self, hero_id: int, period: HeroPeriod, filters: HeroFilters) -> dict[str, Any]:
        data = self.repository.read(period, filters, hero_id=hero_id)
        if not data.hero_exists:
            raise HeroNotFound
        metadata, heroes = self._window(data, period, filters)
        hero = heroes.get(hero_id) or hero_metrics(
            hero_id, 0, 0, metadata["sample"]["matches"], self.min_sample_size
        )
        return {**metadata, "status": "ok" if hero["picks"] else "no_data", "hero": hero}

    def trend(self, hero_id: int, period: HeroPeriod, filters: HeroFilters) -> dict[str, Any]:
        data = self.repository.read(period, filters, hero_id=hero_id, compare=True)
        if not data.hero_exists:
            raise HeroNotFound
        metadata, heroes = self._window(data, period, filters)
        previous, old_heroes = self._window(data, period.previous, filters)
        current = heroes.get(hero_id) or hero_metrics(
            hero_id, 0, 0, metadata["sample"]["matches"], self.min_sample_size
        )
        old = old_heroes.get(hero_id) or hero_metrics(
            hero_id, 0, 0, previous["sample"]["matches"], self.min_sample_size
        )
        daily = {row.day: row for row in data.heroes if row.hero_id == hero_id}
        points = []
        for offset in range(period.days):
            day = period.start + timedelta(days=offset)
            row = daily.get(day)
            matches = data.match_counts.get(day, 0)
            points.append(
                {
                    "date": day,
                    "matches": matches,
                    "has_data": matches > 0,
                    **hero_metrics(
                        hero_id,
                        row.picks if row else 0,
                        row.wins if row else 0,
                        matches,
                        self.min_sample_size,
                    ),
                }
            )
        if not metadata["sample"]["matches"]:
            status = "no_current_data"
        elif previous["sample"]["observed_days"] < period.days:
            status = "insufficient_history"
        elif metadata["sample"]["observed_days"] < period.days:
            status = "incomplete_current_period"
        else:
            status = "comparable"
        deltas = {"pick_rate_delta": None, "win_rate_delta": None}
        if status == "comparable":
            for metric in ("pick_rate", "win_rate"):
                if current[metric] is not None and old[metric] is not None:
                    deltas[f"{metric}_delta"] = current[metric] - old[metric]
        return {
            **metadata,
            "hero": current,
            "points": points,
            "comparison": {
                "status": status,
                "period": previous["period"],
                "sample": previous["sample"],
                "hero": old,
                **deltas,
            },
        }

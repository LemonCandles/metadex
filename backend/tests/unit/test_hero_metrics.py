"""Hand-calculated metrics, sorting and comparable windows without any database."""

from datetime import UTC, date, datetime

import pytest

from app.analytics.heroes import (
    HeroDailyCount,
    HeroFilters,
    HeroNotFound,
    HeroPeriod,
    HeroStatsService,
    PublishedHeroData,
    hero_metrics,
)

pytestmark = pytest.mark.unit


class MemoryRepository:
    def __init__(self, data: PublishedHeroData) -> None:
        self.data = data
        self.calls = []

    def read(self, period, filters, *, hero_id=None, compare=False):
        self.calls.append((period, filters, hero_id, compare))
        return self.data


def make_service(match_counts, rows, *, minimum=3, exists=True):
    data = PublishedHeroData(
        "version_test", datetime(2026, 9, 30, tzinfo=UTC), match_counts, tuple(rows), exists
    )
    return HeroStatsService(MemoryRepository(data), window_days=7, min_sample_size=minimum)


def test_manual_rates_preserve_counts_and_distinct_denominators():
    assert hero_metrics(1, 3, 2, 5, 4) == {
        "hero_id": 1,
        "picks": 3,
        "wins": 2,
        "losses": 1,
        "pick_rate": 0.6,
        "win_rate": 2 / 3,
        "sample_size": 3,
        "meets_min_sample": False,
    }
    assert hero_metrics(1, 0, 0, 5, 1)["pick_rate"] == 0
    assert hero_metrics(1, 0, 0, 5, 1)["win_rate"] is None
    assert hero_metrics(1, 0, 0, 0, 1)["pick_rate"] is None


def test_window_sums_counts_before_division_and_keeps_small_samples_auditable():
    first, second = date(2026, 9, 18), date(2026, 9, 19)
    service = make_service(
        {first: 1, second: 4},
        [
            HeroDailyCount(first, 1, 1, 1),
            HeroDailyCount(second, 1, 3, 1),
            HeroDailyCount(second, 2, 1, 1),
        ],
    )
    period, filters = HeroPeriod(first, date(2026, 9, 20)), HeroFilters(game_mode=22)
    ranking = service.ranking(period, filters)
    assert [hero["hero_id"] for hero in ranking["heroes"]] == [1]
    assert ranking["heroes"][0]["win_rate"] == 0.5  # (1 + 1) / (1 + 3), not (1 + 1/3) / 2.
    assert ranking["heroes"][0]["pick_rate"] == 0.8
    assert ranking["sample"]["matches"] == 5
    assert service.detail(2, period, filters)["hero"]["meets_min_sample"] is False
    audit = service.ranking(period, filters, include_below_min=True)
    assert [hero["hero_id"] for hero in audit["heroes"]] == [2, 1]
    assert service.repository.calls[-1] == (period, filters, None, False)


@pytest.mark.parametrize("order_by", ["picks", "wins", "losses", "pick_rate", "win_rate"])
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_ties_always_use_ascending_hero_id(order_by, order):
    day = date(2026, 9, 18)
    service = make_service(
        {day: 1}, [HeroDailyCount(day, 3, 1, 1), HeroDailyCount(day, 1, 1, 1)], minimum=1
    )
    result = service.ranking(
        HeroPeriod(day, date(2026, 9, 19)), HeroFilters(), order_by=order_by, order=order
    )
    assert [hero["hero_id"] for hero in result["heroes"]] == [1, 3]


def test_default_period_uses_complete_utc_days(monkeypatch):
    monkeypatch.setattr(
        "app.analytics.heroes.utc_now", lambda: datetime(2026, 9, 30, 23, tzinfo=UTC)
    )
    service = make_service({}, [])
    assert service.period(None, None) == HeroPeriod(date(2026, 9, 23), date(2026, 9, 30))
    with pytest.raises(ValueError, match="together"):
        service.period(date(2026, 9, 23), None)


def test_hero_absent_from_period_has_zero_picks_but_keeps_all_eligible_matches():
    day = date(2026, 9, 18)
    service = make_service({day: 2}, [])
    result = service.detail(1, HeroPeriod(day, date(2026, 9, 19)), HeroFilters())
    assert result["status"] == "no_data"
    assert result["sample"]["matches"] == 2
    assert result["hero"]["pick_rate"] == 0
    assert result["hero"]["win_rate"] is None
    with pytest.raises(HeroNotFound):
        make_service({}, [], exists=False).detail(
            999, HeroPeriod(day, date(2026, 9, 19)), HeroFilters()
        )


def test_trend_uses_equal_windows_and_the_same_snapshot_and_filters():
    days = [date(2026, 9, day) for day in range(15, 19)]
    service = make_service(
        dict.fromkeys(days, 2),
        [
            HeroDailyCount(days[0], 1, 1, 0),
            HeroDailyCount(days[1], 1, 1, 1),
            HeroDailyCount(days[2], 1, 2, 2),
            HeroDailyCount(days[3], 1, 1, 1),
        ],
    )
    period, filters = HeroPeriod(days[2], date(2026, 9, 19)), HeroFilters(skill_min=70)
    result = service.trend(1, period, filters)
    assert service.repository.calls == [(period, filters, 1, True)]
    assert result["hero"]["picks"] == 3
    assert result["comparison"]["hero"]["picks"] == 2
    assert result["comparison"]["status"] == "comparable"
    assert result["comparison"]["pick_rate_delta"] == 0.25
    assert result["comparison"]["win_rate_delta"] == 0.5


@pytest.mark.parametrize(
    ("days", "status"),
    [
        ([], "no_current_data"),
        ([17, 18], "insufficient_history"),
        ([15, 16, 17], "incomplete_current_period"),
    ],
)
def test_trend_missing_days_do_not_fabricate_comparisons(days, status):
    service = make_service({date(2026, 9, day): 1 for day in days}, [])
    result = service.trend(1, HeroPeriod(date(2026, 9, 17), date(2026, 9, 19)), HeroFilters())
    assert result["comparison"]["status"] == status
    assert result["comparison"]["pick_rate_delta"] is None
    assert result["comparison"]["win_rate_delta"] is None
    assert len(result["points"]) == 2
    for point in result["points"]:
        if not point["has_data"]:
            assert point["matches"] == 0
            assert point["pick_rate"] is point["win_rate"] is None

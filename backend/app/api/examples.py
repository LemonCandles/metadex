"""Illustrative publication metadata and counts from the first two real fixtures."""

from copy import deepcopy

from fastapi import FastAPI

METADATA_EXAMPLE = {
    "period": {
        "start": "2026-09-18",
        "end": "2026-09-19",
        "timezone": "UTC",
        "end_exclusive": True,
    },
    "filters": {
        "cohort": "all",
        "game_mode": None,
        "lobby_type": None,
        "skill_min": None,
        "skill_max": None,
        "rank_coverage_min": None,
    },
    "updated_at": "2026-09-30T12:00:00Z",
    "version_id": "example_publication",
    "sample": {
        "matches": 2,
        "participants": 20,
        "observed_days": 1,
        "expected_days": 1,
        "min_sample_size": 100,
    },
}
HERO_EXAMPLE = {
    "hero_id": 1,
    "picks": 1,
    "wins": 1,
    "losses": 0,
    "pick_rate": 0.5,
    "win_rate": 1.0,
    "sample_size": 1,
    "meets_min_sample": False,
}
DETAIL_EXAMPLE = {**METADATA_EXAMPLE, "status": "ok", "hero": HERO_EXAMPLE}
RANKING_EXAMPLE = {
    **METADATA_EXAMPLE,
    "status": "below_min_sample",
    "ordering": {"order_by": "win_rate", "order": "desc", "tie_breaker": "hero_id_asc"},
    "include_below_min": False,
    "heroes": [],
}
EMPTY_HERO_EXAMPLE = {
    **HERO_EXAMPLE,
    "picks": 0,
    "wins": 0,
    "pick_rate": None,
    "win_rate": None,
    "sample_size": 0,
}
TREND_EXAMPLE = {
    **METADATA_EXAMPLE,
    "hero": HERO_EXAMPLE,
    "points": [{"date": "2026-09-18", "matches": 2, "has_data": True, **HERO_EXAMPLE}],
    "comparison": {
        "status": "insufficient_history",
        "period": {
            "start": "2026-09-17",
            "end": "2026-09-18",
            "timezone": "UTC",
            "end_exclusive": True,
        },
        "sample": {
            **METADATA_EXAMPLE["sample"],
            "matches": 0,
            "participants": 0,
            "observed_days": 0,
        },
        "hero": EMPTY_HERO_EXAMPLE,
        "pick_rate_delta": None,
        "win_rate_delta": None,
    },
}


def preserve_openapi_examples(application: FastAPI) -> None:
    """Keep explicit nulls: the default OpenAPI encoder omits None in response examples."""
    generate = application.openapi

    def openapi() -> dict:
        document = generate()
        for path, example in (
            ("/api/v1/meta/heroes", RANKING_EXAMPLE),
            ("/api/v1/meta/heroes/{hero_id}", DETAIL_EXAMPLE),
            ("/api/v1/meta/heroes/{hero_id}/trend", TREND_EXAMPLE),
        ):
            content = document["paths"][path]["get"]["responses"]["200"]["content"]
            content["application/json"]["example"] = deepcopy(example)
        return document

    application.openapi = openapi

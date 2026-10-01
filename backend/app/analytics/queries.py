"""Read the published ranking, detail or trend locally without running the web server."""

import argparse
import json
import sys
from dataclasses import fields

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.analytics.heroes import (
    HeroFilters,
    HeroNotFound,
    HeroStatsService,
    RepositoryUnavailable,
)
from app.api.models import HeroQuery, RankingQuery
from app.core.config import get_settings
from app.storage.hero_queries import DuckDBHeroStatsRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("ranking", "detail", "trend"):
        command = commands.add_parser(name)
        if name != "ranking":
            command.add_argument("hero_id", type=int)
        command.add_argument("--period-start")
        command.add_argument("--period-end")
        command.add_argument("--cohort", choices=("all", "high_skill_public_v1"), default="all")
        command.add_argument("--game-mode", type=int)
        command.add_argument("--lobby-type", type=int)
        command.add_argument("--skill-min", type=float)
        command.add_argument("--skill-max", type=float)
        command.add_argument("--rank-coverage-min", type=int)
        if name == "ranking":
            command.add_argument("--order-by", default="win_rate")
            command.add_argument("--order", default="desc")
            command.add_argument("--include-below-min", action="store_true")
    args = vars(parser.parse_args(argv))
    operation = args.pop("command")
    hero_id = args.pop("hero_id", None)
    if hero_id is not None and not 1 <= hero_id <= 2_147_483_647:
        parser.error("hero_id must be a positive 32-bit integer")
    try:
        query = RankingQuery(**args) if operation == "ranking" else HeroQuery(**args)
    except ValidationError as exc:
        parser.error(str(exc))
    settings = get_settings()
    service = HeroStatsService(
        DuckDBHeroStatsRepository(settings.duckdb_path),
        window_days=settings.meta_window_days,
        min_sample_size=settings.min_sample_size,
    )
    period = service.period(query.period_start, query.period_end)
    filters = HeroFilters(
        **{field.name: getattr(query, field.name) for field in fields(HeroFilters)}
    )
    try:
        if operation == "ranking":
            result = service.ranking(
                period,
                filters,
                order_by=query.order_by,
                order=query.order,
                include_below_min=query.include_below_min,
            )
        elif operation == "detail":
            result = service.detail(hero_id, period, filters)
        else:
            result = service.trend(hero_id, period, filters)
    except (RepositoryUnavailable, HeroNotFound) as exc:
        message = (
            "published data unavailable"
            if isinstance(exc, RepositoryUnavailable)
            else ("hero not observed in the current publication")
        )
        print(json.dumps({"error": message}), file=sys.stderr)
        return 1
    print(json.dumps(jsonable_encoder(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

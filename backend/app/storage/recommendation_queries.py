"""Read one published contextual aggregate, with no collection or persistent writes."""

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from app.analytics.heroes import HeroFilters, HeroPeriod, RepositoryUnavailable
from app.analytics.recommendations import (
    ItemTiming,
    PublishedRecommendationData,
    RecommendationContext,
    RecommendationCount,
)


class DuckDBRecommendationRepository:
    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path

    def read(
        self,
        period: HeroPeriod,
        filters: HeroFilters,
        *,
        context: RecommendationContext,
        timing: ItemTiming | None,
    ) -> PublishedRecommendationData:
        if not self.catalog_path.is_file():
            raise RepositoryUnavailable
        conditions = ["stat_date >= ?", "stat_date < ?"]
        parameters: list[object] = [period.start, period.end]
        for column, operator, value in (
            ("game_mode", "=", filters.game_mode),
            ("lobby_type", "=", filters.lobby_type),
            ("avg_rank_tier", ">=", filters.skill_min),
            ("avg_rank_tier", "<=", filters.skill_max),
            ("num_rank_tier", ">=", filters.rank_coverage_min),
            ("duration_seconds", ">=", timing.duration_min_seconds if timing else None),
            ("duration_seconds", "<=", timing.duration_max_seconds if timing else None),
        ):
            if value is not None:
                conditions.append(f"{column} {operator} ?")
                parameters.append(value)
        if filters.skill_min is not None or filters.skill_max is not None:
            conditions.append("num_rank_tier > 0")
        try:
            with closing(duckdb.connect(str(self.catalog_path), read_only=True)) as connection:
                connection.execute("BEGIN TRANSACTION")
                publication = connection.execute(
                    """SELECT v.version_id, epoch_us(v.published_at), v.manifest_json
                    FROM current_publication c JOIN dataset_versions v USING (version_id)
                    WHERE c.singleton = 1 AND v.status = 'published'"""
                ).fetchone()
                if publication is None:
                    raise RepositoryUnavailable
                manifest = json.loads(publication[2])
                if manifest["aggregator_version"] < 3:
                    raise RepositoryUnavailable
                if filters.cohort == "high_skill_public_v1":
                    metadata = manifest.get("metadata")
                    if not metadata:
                        raise RepositoryUnavailable
                    conditions.extend(["avg_rank_tier >= 70", "num_rank_tier >= 5"])
                    for column, key in (
                        ("game_mode", "balanced_game_modes"),
                        ("lobby_type", "balanced_lobby_types"),
                    ):
                        identifiers = metadata[key]
                        if not identifiers:
                            conditions.append("FALSE")
                        else:
                            conditions.append(f"{column} IN ({','.join('?' for _ in identifiers)})")
                            parameters.extend(identifiers)
                known_positions, hero_exists = connection.execute(
                    """SELECT count(*) FILTER (WHERE position IS NOT NULL) > 0,
                        count(*) FILTER (WHERE hero_id = ?) > 0
                    FROM recommendation_stats WHERE kind = 'hero'""",
                    [context.hero_id],
                ).fetchone()
                rows = connection.execute(
                    "SELECT stat_date, hero_id, position, ally_ids, opponent_ids, "
                    "duration_seconds, "
                    "kind, item_key, purchase_index, purchase_time_seconds, sample_size, wins "
                    "FROM recommendation_stats WHERE " + " AND ".join(conditions),
                    parameters,
                ).fetchall()
                connection.execute("COMMIT")
                return PublishedRecommendationData(
                    version_id=publication[0],
                    updated_at=datetime(1970, 1, 1, tzinfo=UTC)
                    + timedelta(microseconds=publication[1]),
                    rows=tuple(
                        RecommendationCount(*row[:3], tuple(row[3]), tuple(row[4]), *row[5:])
                        for row in rows
                    ),
                    position_supported=known_positions,
                    hero_exists=context.hero_id is None or hero_exists,
                )
        except (duckdb.Error, OSError) as exc:
            raise RepositoryUnavailable from exc

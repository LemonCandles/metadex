"""Read-only DuckDB adapter for the storage-independent hero repository contract."""

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from app.analytics.heroes import (
    HeroDailyCount,
    HeroFilters,
    HeroPeriod,
    PublishedHeroData,
    RepositoryUnavailable,
)


class DuckDBHeroStatsRepository:
    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path

    def read(
        self,
        period: HeroPeriod,
        filters: HeroFilters,
        *,
        hero_id: int | None = None,
        compare: bool = False,
    ) -> PublishedHeroData:
        if not self.catalog_path.is_file():
            raise RepositoryUnavailable
        start = period.previous.start if compare else period.start
        conditions = ["started_at_utc >= ?", "started_at_utc < ?"]
        parameters: list[object] = [
            datetime.combine(start, datetime.min.time(), UTC),
            datetime.combine(period.end, datetime.min.time(), UTC),
        ]
        for column, operator, value in (
            ("game_mode", "=", filters.game_mode),
            ("lobby_type", "=", filters.lobby_type),
            ("avg_rank_tier", ">=", filters.skill_min),
            ("avg_rank_tier", "<=", filters.skill_max),
            ("num_rank_tier", ">=", filters.rank_coverage_min),
        ):
            if value is not None:
                conditions.append(f"{column} {operator} ?")
                parameters.append(value)
        if filters.skill_min is not None or filters.skill_max is not None:
            conditions.append("num_rank_tier > 0")
        try:
            with closing(duckdb.connect(str(self.catalog_path), read_only=True)) as connection:
                connection.execute("SET TimeZone = 'UTC'")
                connection.execute("BEGIN TRANSACTION")
                publication = connection.execute(
                    """SELECT v.version_id, epoch_us(v.published_at), v.manifest_json
                    FROM current_publication c
                    JOIN dataset_versions v USING (version_id)
                    WHERE c.singleton = 1 AND v.status = 'published'"""
                ).fetchone()
                if publication is None:
                    raise RepositoryUnavailable
                manifest = json.loads(publication[2])
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
                eligible = "SELECT * FROM matches WHERE " + " AND ".join(conditions)
                hero_exists = (
                    hero_id is None
                    or connection.execute(
                        "SELECT EXISTS (SELECT 1 FROM match_players WHERE hero_id = ?)", [hero_id]
                    ).fetchone()[0]
                )
                match_counts = dict(
                    connection.execute(
                        f"""WITH eligible AS ({eligible})
                    SELECT CAST(started_at_utc AS DATE), count(*) FROM eligible GROUP BY 1""",
                        parameters,
                    ).fetchall()
                )
                hero_condition = "WHERE p.hero_id = ?" if hero_id is not None else ""
                if filters == HeroFilters() and manifest["aggregator_version"] >= 2:
                    rows = connection.execute(
                        f"""SELECT stat_date, hero_id, picks, wins FROM hero_daily_stats
                        WHERE stat_date >= ? AND stat_date < ?
                        {"AND hero_id = ?" if hero_id is not None else ""}
                        ORDER BY stat_date, hero_id""",
                        [start, period.end, hero_id]
                        if hero_id is not None
                        else [start, period.end],
                    ).fetchall()
                else:
                    rows = connection.execute(
                        f"""WITH eligible AS ({eligible})
                    SELECT CAST(m.started_at_utc AS DATE), p.hero_id, count(*),
                        count(*) FILTER (WHERE p.won)
                    FROM eligible m JOIN match_players p USING (match_id)
                    {hero_condition} GROUP BY 1, 2 ORDER BY 1, 2""",
                        [*parameters, hero_id] if hero_id is not None else parameters,
                    ).fetchall()
                connection.execute("COMMIT")
                return PublishedHeroData(
                    version_id=publication[0],
                    updated_at=datetime(1970, 1, 1, tzinfo=UTC)
                    + timedelta(microseconds=publication[1]),
                    match_counts=match_counts,
                    heroes=tuple(HeroDailyCount(*row) for row in rows),
                    hero_exists=hero_exists,
                )
        except (duckdb.Error, OSError) as exc:
            raise RepositoryUnavailable from exc

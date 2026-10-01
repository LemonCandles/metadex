"""Reproducible daily counts materialized before a publication is promoted."""

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from app.core.errors import DataError

HERO_DAILY_SCHEMA = pa.schema(
    [
        ("stat_date", pa.date32()),
        ("hero_id", pa.int32()),
        ("picks", pa.int64()),
        ("wins", pa.int64()),
        ("losses", pa.int64()),
        ("matches", pa.int64()),
        ("pick_rate", pa.float64()),
        ("win_rate", pa.float64()),
    ]
)


def daily_stats_sql(*, prefix: str = "") -> str:
    if prefix not in ("", "candidate_"):
        raise ValueError("unsupported table prefix")
    return f"""
        WITH daily_matches AS (
            SELECT CAST(started_at_utc AS DATE) stat_date, count(*) matches
            FROM {prefix}matches GROUP BY 1
        ), daily_heroes AS (
            SELECT CAST(m.started_at_utc AS DATE) stat_date, p.hero_id,
                count(*) picks, count(*) FILTER (WHERE p.won) wins
            FROM {prefix}matches m JOIN {prefix}match_players p USING (match_id)
            GROUP BY 1, 2
        )
        SELECT h.stat_date, h.hero_id, h.picks, h.wins, h.picks - h.wins losses,
            d.matches, h.picks::DOUBLE / d.matches pick_rate,
            h.wins::DOUBLE / h.picks win_rate
        FROM daily_heroes h JOIN daily_matches d USING (stat_date)
        ORDER BY h.stat_date, h.hero_id
    """


def write_hero_daily_stats(connection: duckdb.DuckDBPyConnection, destination: Path) -> None:
    rows = connection.execute(daily_stats_sql(prefix="candidate_")).fetchall()
    table = pa.Table.from_pylist(
        [dict(zip(HERO_DAILY_SCHEMA.names, row, strict=True)) for row in rows],
        schema=HERO_DAILY_SCHEMA,
    )
    pq.write_table(table, destination / "hero_daily_stats.parquet")


def validate_hero_daily_stats(connection: duckdb.DuckDBPyConnection) -> None:
    expected = daily_stats_sql(prefix="candidate_")
    differs = connection.execute(f"""
        WITH expected AS ({expected}) SELECT EXISTS (
            (SELECT * FROM expected EXCEPT ALL SELECT * FROM candidate_hero_daily_stats)
            UNION ALL
            (SELECT * FROM candidate_hero_daily_stats EXCEPT ALL SELECT * FROM expected)
        )
    """).fetchone()[0]
    if differs:
        raise DataError("hero_daily_stats do not match normalized matches and participants")

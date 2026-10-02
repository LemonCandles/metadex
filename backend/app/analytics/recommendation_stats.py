"""Materialize observed contexts, never invent combinations or infer economic positions."""

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from app.core.errors import DataError

RECOMMENDATION_SCHEMA = pa.schema(
    [
        ("stat_date", pa.date32()),
        ("game_mode", pa.int32()),
        ("lobby_type", pa.int32()),
        ("avg_rank_tier", pa.float64()),
        ("num_rank_tier", pa.int8()),
        ("hero_id", pa.int32()),
        ("position", pa.int8()),
        ("ally_ids", pa.list_(pa.int32())),
        ("opponent_ids", pa.list_(pa.int32())),
        ("duration_seconds", pa.int32()),
        ("kind", pa.string()),
        ("item_key", pa.string()),
        ("purchase_index", pa.int32()),
        ("purchase_time_seconds", pa.int32()),
        ("sample_size", pa.int64()),
        ("wins", pa.int64()),
    ]
)


def recommendation_stats_sql(*, prefix: str = "") -> str:
    if prefix not in ("", "candidate_"):
        raise ValueError("unsupported table prefix")
    return f"""
        WITH participants AS (
            SELECT CAST(m.started_at_utc AS DATE) stat_date,
                m.game_mode, m.lobby_type, m.avg_rank_tier, m.num_rank_tier,
                p.match_id, p.player_slot, p.hero_id, p.position, p.won,
                list(q.hero_id ORDER BY q.hero_id)
                    FILTER (WHERE q.team = p.team AND q.hero_id <> p.hero_id) ally_ids,
                list(q.hero_id ORDER BY q.hero_id)
                    FILTER (WHERE q.team <> p.team) opponent_ids,
                m.duration_seconds
            FROM {prefix}matches m JOIN {prefix}match_players p USING (match_id)
            JOIN {prefix}match_players q ON q.match_id = p.match_id
            GROUP BY ALL
        ), first_purchases AS (
            SELECT i.* FROM {prefix}player_items i
            JOIN {prefix}matches m USING (match_id)
            WHERE i.source_kind = 'purchase_log' AND i.item_key IS NOT NULL
                AND NOT starts_with(i.item_key, 'recipe_') AND i.purchase_index >= 0
                AND i.purchase_time_seconds <= m.duration_seconds
            QUALIFY row_number() OVER (
                PARTITION BY i.match_id, i.player_slot, i.item_key
                ORDER BY i.purchase_time_seconds, i.purchase_index
            ) = 1
        ), observations AS (
            SELECT p.*, 'hero' kind, NULL::VARCHAR item_key,
                NULL::INTEGER purchase_index, NULL::INTEGER purchase_time_seconds
            FROM participants p
            UNION ALL
            SELECT p.*, 'item' kind, i.item_key, i.purchase_index, i.purchase_time_seconds
            FROM participants p JOIN first_purchases i USING (match_id, player_slot)
        )
        SELECT stat_date, game_mode, lobby_type, avg_rank_tier, num_rank_tier,
            hero_id, position, ally_ids, opponent_ids, duration_seconds, kind,
            item_key, purchase_index, purchase_time_seconds,
            count(*) sample_size, count(*) FILTER (WHERE won) wins
        FROM observations GROUP BY ALL
        ORDER BY stat_date, game_mode, lobby_type, avg_rank_tier, num_rank_tier,
            hero_id, position, ally_ids, opponent_ids, duration_seconds, kind,
            item_key, purchase_index, purchase_time_seconds
    """


def write_recommendation_stats(connection: duckdb.DuckDBPyConnection, destination: Path) -> None:
    rows = connection.execute(recommendation_stats_sql(prefix="candidate_")).fetchall()
    table = pa.Table.from_pylist(
        [dict(zip(RECOMMENDATION_SCHEMA.names, row, strict=True)) for row in rows],
        schema=RECOMMENDATION_SCHEMA,
    )
    pq.write_table(table, destination / "recommendation_stats.parquet")


def validate_recommendation_stats(connection: duckdb.DuckDBPyConnection) -> None:
    expected = recommendation_stats_sql(prefix="candidate_")
    differs = connection.execute(f"""
        WITH expected AS ({expected}) SELECT EXISTS (
            (SELECT * FROM expected EXCEPT ALL SELECT * FROM candidate_recommendation_stats)
            UNION ALL
            (SELECT * FROM candidate_recommendation_stats EXCEPT ALL SELECT * FROM expected)
        )
    """).fetchone()[0]
    if differs:
        raise DataError("recommendation_stats do not match normalized participants and purchases")

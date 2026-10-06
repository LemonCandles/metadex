"""Explainable rankings over immutable counts, with one explicit fallback for the whole list."""

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Any, Literal, Protocol

from app.analytics.heroes import HeroFilters, HeroNotFound, HeroPeriod, resolve_period


@dataclass(frozen=True)
class RecommendationContext:
    hero_id: int | None = None
    position: int | None = None
    ally_ids: tuple[int, ...] = ()
    opponent_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ItemTiming:
    duration_min_seconds: int | None = None
    duration_max_seconds: int | None = None
    purchase_time_min_seconds: int | None = None
    purchase_time_max_seconds: int = 1200
    purchase_index_min: int | None = None
    purchase_index_max: int | None = None


@dataclass(frozen=True)
class RecommendationCount:
    day: date
    hero_id: int
    position: int | None
    ally_ids: tuple[int, ...]
    opponent_ids: tuple[int, ...]
    duration_seconds: int
    kind: Literal["hero", "item"]
    item_key: str | None
    purchase_index: int | None
    purchase_time_seconds: int | None
    sample_size: int
    wins: int


@dataclass(frozen=True)
class PublishedRecommendationData:
    version_id: str
    updated_at: datetime
    rows: tuple[RecommendationCount, ...]
    position_supported: bool
    hero_exists: bool = True


class RecommendationRepository(Protocol):
    def read(
        self,
        period: HeroPeriod,
        filters: HeroFilters,
        *,
        context: RecommendationContext,
        timing: ItemTiming | None,
    ) -> PublishedRecommendationData: ...


def context_matches(row: RecommendationCount, context: RecommendationContext) -> bool:
    return (
        (context.hero_id is None or row.hero_id == context.hero_id)
        and (context.position is None or row.position == context.position)
        and set(context.ally_ids).issubset(row.ally_ids)
        and set(context.opponent_ids).issubset(row.opponent_ids)
    )


def context_levels(context: RecommendationContext, allow_fallback: bool):
    """Keep opponents until the last level; never relax position, hero, dates or meta."""
    yield "exact", context, []
    if not allow_fallback:
        return
    removed = []
    if context.ally_ids:
        context = replace(context, ally_ids=())
        removed.append("ally_ids")
        yield "without_allies", context, removed.copy()
    if context.opponent_ids:
        context = replace(context, opponent_ids=())
        removed.append("opponent_ids")
        yield "without_draft", context, removed.copy()


def timing_matches(row: RecommendationCount, timing: ItemTiming) -> bool:
    for value, minimum, maximum in (
        (
            row.purchase_time_seconds,
            timing.purchase_time_min_seconds,
            timing.purchase_time_max_seconds,
        ),
        (row.purchase_index, timing.purchase_index_min, timing.purchase_index_max),
    ):
        if value is None or (minimum is not None and value < minimum):
            return False
        if maximum is not None and value > maximum:
            return False
    return True


class RecommendationService:
    def __init__(
        self, repository: RecommendationRepository, *, window_days: int, min_sample_size: int
    ) -> None:
        self.repository = repository
        self.window_days = window_days
        self.min_sample_size = min_sample_size

    def period(self, start: date | None, end: date | None) -> HeroPeriod:
        return resolve_period(start, end, self.window_days)

    def recommend(
        self,
        kind: Literal["hero", "item"],
        period: HeroPeriod,
        filters: HeroFilters,
        context: RecommendationContext,
        *,
        allow_fallback: bool = True,
        limit: int = 10,
        timing: ItemTiming | None = None,
    ) -> dict[str, Any]:
        data = self.repository.read(period, filters, context=context, timing=timing)
        if not data.hero_exists:
            raise HeroNotFound
        hero_rows = [row for row in data.rows if row.kind == "hero"]
        participants = sum(row.sample_size for row in hero_rows)
        limitations = [
            "Associação observada com vitórias; não demonstra causalidade nem prevê a partida.",
            "A amostra coletada não representa todas as partidas da OpenDota.",
            "As funções Carry, Mid, Offlane, Soft Support e Hard Support não são deduzidas "
            "apenas da rota; participantes sem função conhecida são excluídos desse filtro.",
            "O período não separa patches do Dota 2 e pode misturar versões do jogo.",
        ]
        if kind == "item":
            limitations.extend(
                [
                    "Somente a primeira compra registrada de cada item por participante é contada; "
                    "receitas, inventário final e compras após o fim da partida são excluídos.",
                    "Compras podem refletir vantagem anterior e sobrevivência até a compra. "
                    "Duração, tempo e ordem refinam o recorte, mas não eliminam esse viés.",
                    "O histórico de compras pode ser incompleto; ausência de compra "
                    "registrada não significa que o item nunca foi adquirido.",
                ]
            )
        result = {
            "period": period.as_dict(),
            "filters": asdict(filters),
            "version_id": data.version_id,
            "updated_at": data.updated_at,
            "sample": {
                "matches": participants // 10,
                "participants": participants,
                "observed_days": len({row.day for row in hero_rows}),
                "expected_days": period.days,
                "min_sample_size": self.min_sample_size,
            },
            "requested_context": asdict(context),
            "used_context": asdict(context),
            "supported_contexts": {
                "position": data.position_supported,
                "allies": True,
                "opponents": True,
                "hero": kind == "item",
            },
            "item_timing": asdict(timing) if timing else None,
            "ordering": {
                "order_by": "win_rate_desc",
                "tie_breakers": [
                    "sample_size_desc",
                    "hero_id_asc" if kind == "hero" else "item_key_asc",
                ],
            },
            "fallback": {
                "allowed": allow_fallback,
                "applied": False,
                "removed_filters": [],
                "attempts": [],
            },
            "limitations": limitations,
            "recommendations": [],
            "status": "no_data" if not participants else "insufficient_evidence",
            "explanation": (
                "Nenhum candidato atingiu a amostra mínima no contexto consultado."
                if participants
                else "Não há partidas elegíveis no período e recorte consultados."
            ),
        }
        if context.position is not None and not data.position_supported:
            result.update(
                status="unsupported_context",
                explanation="Os dados não informam a função dos jogadores no time; "
                "o filtro não foi removido e nenhuma sugestão foi produzida.",
            )
            return result
        excluded = set(context.ally_ids) | set(context.opponent_ids)
        for level, used, removed in context_levels(context, allow_fallback):
            level_label = {
                "exact": "draft informado",
                "without_allies": "draft sem filtro de aliados",
                "without_draft": "sem filtros de aliados e inimigos",
            }[level]
            context_size = sum(row.sample_size for row in hero_rows if context_matches(row, used))
            totals: dict[int | str, dict[str, Any]] = {}
            for row in data.rows:
                if row.kind != kind or not context_matches(row, used):
                    continue
                if kind == "hero" and row.hero_id in excluded:
                    continue
                if kind == "item" and (timing is None or not timing_matches(row, timing)):
                    continue
                key = row.hero_id if kind == "hero" else row.item_key
                if key is None:
                    continue
                counts = totals.setdefault(
                    key, {"sample_size": 0, "wins": 0, "duration": 0, "time": 0, "index": 0}
                )
                counts["sample_size"] += row.sample_size
                counts["wins"] += row.wins
                counts["duration"] += row.duration_seconds * row.sample_size
                counts["time"] += (row.purchase_time_seconds or 0) * row.sample_size
                counts["index"] += (row.purchase_index or 0) * row.sample_size
            eligible = []
            for key, counts in totals.items():
                size, wins = counts["sample_size"], counts["wins"]
                if size < self.min_sample_size:
                    continue
                suggestion = {
                    "hero_id": key if kind == "hero" else context.hero_id,
                    "item_key": key if kind == "item" else None,
                    "sample_size": size,
                    "wins": wins,
                    "losses": size - wins,
                    "win_rate": wins / size,
                    "meets_min_sample": True,
                    "context_sample_size": context_size,
                    "context": asdict(used),
                    "explanation": f"{wins} vitórias em {size} participações observadas "
                    f"com {level_label}; taxa = {wins}/{size}.",
                    "mean_duration_seconds": counts["duration"] / size,
                    "mean_purchase_time_seconds": counts["time"] / size if kind == "item" else None,
                    "mean_purchase_index": counts["index"] / size if kind == "item" else None,
                }
                eligible.append(suggestion)
            eligible.sort(
                key=lambda item: (
                    -item["win_rate"],
                    -item["sample_size"],
                    item["hero_id"] if kind == "hero" else item["item_key"],
                )
            )
            result["fallback"]["attempts"].append(
                {
                    "level": level,
                    "context": asdict(used),
                    "context_sample_size": context_size,
                    "candidate_count": len(totals),
                    "eligible_count": len(eligible),
                }
            )
            result["used_context"] = asdict(used)
            if eligible:
                result["recommendations"] = eligible[:limit]
                result["status"] = "ok"
                result["fallback"]["applied"] = bool(removed)
                result["fallback"]["removed_filters"] = removed
                result["explanation"] = (
                    f"Sugestões com {level_label}, ordenadas por win rate e quantidade "
                    "de partidas. Todas usam os mesmos filtros e atingem a amostra mínima."
                )
                return result
        # No broadened ranking was used, even if broader contexts were examined.
        result["used_context"] = asdict(context)
        return result

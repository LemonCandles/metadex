"""Pure OpenDota payload validation and normalization."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any


class InvalidMatch(ValueError):
    """A source record cannot safely enter the processed datasets."""


@dataclass(frozen=True)
class Normalized:
    matches: list[dict[str, Any]]
    match_players: list[dict[str, Any]]
    player_items: list[dict[str, Any]]
    quality: dict[str, Any]


def _integer(value: Any, name: str, *, minimum: int = 0, maximum: int = 2_147_483_647) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidMatch(f"{name}: expected integer in {minimum}..{maximum}")
    return value


def _optional_integer(
    source: dict[str, Any], name: str, missing: Counter[str], *, minimum: int = 0
) -> int | None:
    value = source.get(name)
    if value is None:
        missing[name] += 1
        return None
    return _integer(value, name, minimum=minimum)


def _required(source: dict[str, Any], name: str) -> Any:
    if name not in source or source[name] is None:
        raise InvalidMatch(f"{name}: required field missing")
    return source[name]


def _optional_rank(source: dict[str, Any], missing: Counter[str]) -> float | None:
    value = source.get("avg_rank_tier")
    if value is None:
        missing["avg_rank_tier"] += 1
        return None
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 85:
        raise InvalidMatch("avg_rank_tier: expected finite number in 0..85")
    return float(value)


def _match_row(payload: dict[str, Any], missing: Counter[str]) -> dict[str, Any]:
    match_id = _integer(
        _required(payload, "match_id"), "match_id", minimum=1, maximum=9_223_372_036_854_775_807
    )
    start_time = _integer(
        _required(payload, "start_time"), "start_time", minimum=1, maximum=253_402_300_799
    )
    try:
        started_at = datetime.fromtimestamp(start_time, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise InvalidMatch("start_time: outside supported date range") from exc
    radiant_win = _required(payload, "radiant_win")
    if type(radiant_win) is not bool:
        raise InvalidMatch("radiant_win: expected boolean")
    rank = _optional_rank(payload, missing)
    rank_count = _optional_integer(payload, "num_rank_tier", missing)
    if rank_count is not None and rank_count > 10:
        raise InvalidMatch("num_rank_tier: expected integer <= 10")
    return {
        "match_id": match_id,
        "started_at_utc": started_at,
        "duration_seconds": _integer(_required(payload, "duration"), "duration", minimum=1),
        "radiant_win": radiant_win,
        "game_mode": _integer(_required(payload, "game_mode"), "game_mode"),
        "lobby_type": _integer(_required(payload, "lobby_type"), "lobby_type"),
        "avg_rank_tier": rank,
        "num_rank_tier": rank_count,
        "cluster": _optional_integer(payload, "cluster", missing),
        "source_kind": "match_detail" if "players" in payload else "public_match",
    }


def _public_players(
    payload: dict[str, Any], match: dict[str, Any], missing: Counter[str]
) -> list[dict[str, Any]]:
    result = []
    hero_ids = set()
    for team, field in (("radiant", "radiant_team"), ("dire", "dire_team")):
        heroes = _required(payload, field)
        if not isinstance(heroes, list) or len(heroes) != 5:
            raise InvalidMatch(f"{field}: expected five heroes")
        for index, hero in enumerate(heroes):
            hero_id = _integer(hero, f"{field}[{index}]", minimum=1)
            if hero_id in hero_ids:
                raise InvalidMatch("hero_id: duplicate hero in match")
            hero_ids.add(hero_id)
            result.append(
                {
                    "match_id": match["match_id"],
                    "player_slot": None,
                    "team_index": index,
                    "hero_id": hero_id,
                    "team": team,
                    "won": match["radiant_win"] if team == "radiant" else not match["radiant_win"],
                    "position": None,
                    "lane_role": None,
                }
            )
    missing["position"] += 10
    missing["lane_role"] += 10
    missing["inventory"] += 10
    missing["purchase_log"] += 10
    return result


def _detail_players(
    payload: dict[str, Any], match: dict[str, Any], missing: Counter[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    players = _required(payload, "players")
    if not isinstance(players, list) or len(players) != 10:
        raise InvalidMatch("players: expected ten participants")
    human_players = _optional_integer(payload, "human_players", missing)
    if human_players is not None and human_players != 10:
        raise InvalidMatch("human_players: expected ten")
    result = []
    items = []
    slots: set[int] = set()
    heroes: set[int] = set()
    teams = Counter()
    for index, player in enumerate(players):
        if not isinstance(player, dict):
            raise InvalidMatch(f"players[{index}]: expected object")
        slot = _integer(_required(player, "player_slot"), "player_slot")
        if slot not in (*range(5), *range(128, 133)) or slot in slots:
            raise InvalidMatch("player_slot: invalid or duplicate")
        slots.add(slot)
        team = "radiant" if slot < 128 else "dire"
        teams[team] += 1
        hero = _integer(_required(player, "hero_id"), "hero_id", minimum=1)
        if hero in heroes:
            raise InvalidMatch("hero_id: duplicate hero in match")
        heroes.add(hero)
        won = match["radiant_win"] if team == "radiant" else not match["radiant_win"]
        if "isRadiant" in player and (
            type(player["isRadiant"]) is not bool or player["isRadiant"] != (team == "radiant")
        ):
            raise InvalidMatch("isRadiant: conflicts with player_slot")
        if "win" in player and (type(player["win"]) is not int or player["win"] != int(won)):
            raise InvalidMatch("win: conflicts with match result")
        lane_role = _optional_integer(player, "lane_role", missing, minimum=1)
        if lane_role is not None and lane_role > 4:
            raise InvalidMatch("lane_role: expected 1..4")
        missing["position"] += 1  # lane_role is a lane estimate, not a position 1..5.
        result.append(
            {
                "match_id": match["match_id"],
                "player_slot": slot,
                "team_index": slot if team == "radiant" else slot - 128,
                "hero_id": hero,
                "team": team,
                "won": won,
                "position": None,
                "lane_role": lane_role,
            }
        )
        inventory_seen = False
        for item_slot in (*range(6), "neutral"):
            field = f"item_{item_slot}"
            item_id = _optional_integer(player, field, missing)
            if item_id is None:
                continue
            inventory_seen = True
            if item_id > 0:  # Zero means an observed empty slot.
                items.append(
                    {
                        "match_id": match["match_id"],
                        "player_slot": slot,
                        "item_id": item_id,
                        "item_key": None,
                        "source_kind": "final_inventory",
                        "slot": str(item_slot),
                        "purchase_index": None,
                        "purchase_time_seconds": None,
                    }
                )
        if not inventory_seen:
            missing["inventory"] += 1
        purchase_log = player.get("purchase_log")
        if purchase_log is None:
            missing["purchase_log"] += 1
        elif not isinstance(purchase_log, list):
            raise InvalidMatch("purchase_log: expected list or null")
        else:
            for purchase_index, purchase in enumerate(purchase_log):
                if not isinstance(purchase, dict):
                    raise InvalidMatch("purchase_log: expected objects")
                key = _required(purchase, "key")
                if not isinstance(key, str) or not key.strip():
                    raise InvalidMatch("purchase_log.key: expected nonempty string")
                purchase_time = purchase.get("time")
                if purchase_time is None:
                    raise InvalidMatch("purchase_log.time: required field missing")
                items.append(
                    {
                        "match_id": match["match_id"],
                        "player_slot": slot,
                        "item_id": None,  # Preserve purchase keys without a catalog ID lookup.
                        "item_key": key,
                        "source_kind": "purchase_log",
                        "slot": None,
                        "purchase_index": purchase_index,
                        "purchase_time_seconds": _integer(
                            purchase_time, "purchase_log.time", minimum=-2_147_483_648
                        ),
                    }
                )
    if teams != {"radiant": 5, "dire": 5}:
        raise InvalidMatch("players: expected five participants per team")
    return result, items


def normalize(payloads: list[dict[str, Any]]) -> Normalized:
    """Return deterministic rows and quality counts without changing source payloads."""
    matches: list[dict[str, Any]] = []
    players: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    missing: Counter[str] = Counter()
    seen: set[int] = set()
    for payload in payloads:
        local_missing: Counter[str] = Counter()
        try:
            if not isinstance(payload, dict):
                raise InvalidMatch("payload: expected object")
            match = _match_row(payload, local_missing)
            if match["match_id"] in seen:
                raise InvalidMatch("match_id: duplicate in input")
            if match["source_kind"] == "match_detail":
                match_players, player_items = _detail_players(payload, match, local_missing)
            else:
                match_players = _public_players(payload, match, local_missing)
                player_items = []
        except InvalidMatch as exc:
            rejected.append(
                {
                    "match_id": payload.get("match_id")
                    if isinstance(payload, dict) and type(payload.get("match_id")) is int
                    else None,
                    "reason": str(exc),
                }
            )
            continue
        seen.add(match["match_id"])
        missing.update(local_missing)
        matches.append(match)
        players.extend(match_players)
        items.extend(player_items)
    return Normalized(
        matches,
        players,
        items,
        {
            "input_matches": len(payloads),
            "accepted_matches": len(matches),
            "rejected_matches": len(rejected),
            "accepted_match_players": len(players),
            "accepted_player_items": len(items),
            "missing_fields": dict(sorted(missing.items())),
            "rejections": rejected,
        },
    )

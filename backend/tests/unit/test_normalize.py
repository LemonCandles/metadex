"""Pure, deterministic checks for the processed entity contracts."""

from copy import deepcopy

import pytest

from app.analytics.normalize import normalize

pytestmark = pytest.mark.unit


def test_public_match_produces_ten_players_without_invented_items(load_opendota_fixture):
    source = load_opendota_fixture("public_matches_high_skill.json")[1]
    original = deepcopy(source)
    result = normalize([source])
    assert source == original
    assert result.quality["accepted_matches"] == 1
    assert result.quality["rejected_matches"] == 0
    assert len(result.match_players) == 10
    assert result.player_items == []
    assert result.match_players[0]["team"] == "radiant"
    assert result.match_players[0]["won"] is True
    assert result.match_players[0]["player_slot"] is None
    assert result.match_players[0]["team_index"] == 0
    assert result.match_players[5]["team"] == "dire"
    assert result.match_players[5]["won"] is False
    assert all(player["position"] is None for player in result.match_players)
    assert result.quality["missing_fields"]["inventory"] == 10
    assert result.quality["missing_fields"]["purchase_log"] == 10


def test_detail_keeps_final_inventory_and_purchase_events_separate(load_opendota_fixture):
    source = load_opendota_fixture("match_detail_parsed.json")
    result = normalize([source])
    assert result.quality["accepted_matches"] == 1
    assert len(result.match_players) == 10
    assert result.match_players[0]["lane_role"] == 2
    assert result.match_players[0]["position"] is None
    inventory = [row for row in result.player_items if row["source_kind"] == "final_inventory"]
    purchases = [row for row in result.player_items if row["source_kind"] == "purchase_log"]
    assert all(row["item_id"] > 0 and row["purchase_time_seconds"] is None for row in inventory)
    assert len(purchases) == 50
    assert purchases[0]["item_key"] == "tango"
    assert purchases[0]["item_id"] is None
    assert purchases[0]["purchase_time_seconds"] == -50
    assert purchases[0]["purchase_index"] == 0
    assert result.quality["missing_fields"]["position"] == 10


def test_unparsed_detail_preserves_unknown_purchase_time(load_opendota_fixture):
    result = normalize([load_opendota_fixture("match_detail_unparsed.json")])
    assert result.quality["accepted_matches"] == 1
    assert not any(row["source_kind"] == "purchase_log" for row in result.player_items)
    assert result.quality["missing_fields"]["purchase_log"] == 10
    assert result.quality["missing_fields"]["lane_role"] == 10


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda p: p.update(duration=0), "duration"),
        (lambda p: p.update(radiant_win=1), "radiant_win"),
        (lambda p: p.update(start_time="yesterday"), "start_time"),
        (lambda p: p["radiant_team"].pop(), "radiant_team"),
        (lambda p: p["dire_team"].__setitem__(0, p["radiant_team"][0]), "duplicate hero"),
        (lambda p: p.pop("match_id"), "match_id"),
    ],
)
def test_invalid_public_match_is_rejected_as_a_whole(load_opendota_fixture, change, reason):
    source = load_opendota_fixture("public_matches_high_skill.json")[1]
    change(source)
    result = normalize([source])
    assert result.matches == result.match_players == result.player_items == []
    assert result.quality["rejected_matches"] == 1
    assert reason in result.quality["rejections"][0]["reason"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda p: p["players"].pop(), "ten participants"),
        (lambda p: p["players"][0].update(player_slot=1), "duplicate"),
        (lambda p: p["players"][0].update(isRadiant=False), "isRadiant"),
        (lambda p: p["players"][0].update(win=0), "win"),
        (lambda p: p["players"][0].update(item_0="116"), "item_0"),
        (
            lambda p: p["players"][0].update(purchase_log=[{"key": "tango", "time": None}]),
            "purchase_log.time",
        ),
    ],
)
def test_invalid_detail_is_rejected_without_orphan_rows(load_opendota_fixture, change, reason):
    source = load_opendota_fixture("match_detail_parsed.json")
    change(source)
    result = normalize([source])
    assert result.quality["accepted_matches"] == 0
    assert result.match_players == result.player_items == []
    assert reason in result.quality["rejections"][0]["reason"]


def test_normalization_is_reproducible_and_counts_missing_optional_fields(load_opendota_fixture):
    source = load_opendota_fixture("public_matches_high_skill.json")[1]
    del source["cluster"]
    del source["avg_rank_tier"]
    first = normalize([source, source])
    assert first == normalize([source, source])
    assert first.quality["accepted_matches"] == 1
    assert first.quality["rejected_matches"] == 1
    assert first.quality["missing_fields"]["cluster"] == 1
    assert first.matches[0]["cluster"] is None
    assert first.matches[0]["avg_rank_tier"] is None


def test_fractional_rank_is_preserved_but_nonfinite_rank_is_rejected(load_opendota_fixture):
    source = load_opendota_fixture("public_matches_high_skill.json")[1]
    source["avg_rank_tier"] = 73.5
    assert normalize([source]).matches[0]["avg_rank_tier"] == 73.5
    source["avg_rank_tier"] = float("nan")
    assert normalize([source]).quality["rejections"][0]["reason"].startswith("avg_rank_tier")

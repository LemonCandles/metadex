"""Serve labels from the published snapshot without fetching external metadata."""

from copy import deepcopy

import httpx
import pytest

from app.collectors.metadata import MetadataResult
from app.collectors.opendota import OpenDotaClient
from app.core.config import Settings
from app.core.paths import get_data_paths
from app.core.runs import RunRecord, RunStatus
from app.main import create_app
from app.pipeline import run_pipeline
from app.storage.metadata import persist_metadata

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        duckdb_path=tmp_path / "catalog" / "metadex.duckdb",
    )


def archive_names(settings, fixture):
    run = RunRecord(operation="collect_metadata", requested_count=4)
    run.received_count = run.processed_count = 4
    run.finish(RunStatus.SUCCEEDED)
    result = MetadataResult(
        run,
        {
            "heroes": fixture["heroes"],
            "items": fixture["items"],
            "game_mode": fixture["game_modes"],
            "lobby_type": fixture["lobby_types"],
        },
        [],
        "offline fixture",
    )
    persist_metadata(get_data_paths(settings).raw, result)


async def publish_sample(settings, load_opendota_fixture):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:2]
    async with OpenDotaClient(
        settings, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample))
    ) as source:
        result = await run_pipeline(settings, collect=True, count=2, max_pages=1, client=source)
    assert result.run.status is RunStatus.SUCCEEDED, result.message
    return result


async def request_catalog(settings, resource="heroes"):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as client:
        return await client.get(f"/api/v1/catalog/{resource}")


async def test_catalog_uses_names_and_ids_of_the_published_version(settings, load_opendota_fixture):
    constants = load_opendota_fixture("constants.json")
    archive_names(settings, constants)
    publication = await publish_sample(settings, load_opendota_fixture)
    # A newer raw capture must not silently alter labels belonging to the current publication.
    unpublished = deepcopy(constants)
    unpublished["heroes"]["46"]["localized_name"] = "Unpublished name"
    archive_names(settings, unpublished)
    response = await request_catalog(settings)
    assert response.status_code == 200
    assert response.json() == {
        "version_id": publication.version_id,
        "heroes": [
            {"hero_id": 46, "name": "Templar Assassin"},
            {"hero_id": 55, "name": "Dark Seer"},
            {"hero_id": 84, "name": "Ogre Magi"},
            {"hero_id": 93, "name": "Slark"},
        ],
    }


@pytest.mark.parametrize("resource", ["heroes", "items"])
async def test_publication_without_metadata_returns_an_empty_catalog(
    settings, load_opendota_fixture, resource
):
    publication = await publish_sample(settings, load_opendota_fixture)
    response = await request_catalog(settings, resource)
    assert response.status_code == 200
    assert response.json() == {"version_id": publication.version_id, resource: []}


@pytest.mark.parametrize("resource", ["heroes", "items"])
async def test_no_publication_returns_the_existing_unavailable_error(settings, resource):
    response = await request_catalog(settings, resource)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "data_unavailable"


@pytest.mark.parametrize("resource", ["heroes", "items"])
async def test_modified_published_catalog_is_rejected(settings, load_opendota_fixture, resource):
    archive_names(settings, load_opendota_fixture("constants.json"))
    publication = await publish_sample(settings, load_opendota_fixture)
    metadata = (
        settings.data_dir / "processed" / "versions" / publication.version_id / "metadata.json"
    )
    metadata.write_text("{}\n", encoding="utf-8")
    response = await request_catalog(settings, resource)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "data_unavailable"


async def test_item_names_come_from_the_published_catalog(settings, load_opendota_fixture):
    constants = load_opendota_fixture("constants.json")
    archive_names(settings, constants)
    publication = await publish_sample(settings, load_opendota_fixture)
    unpublished = deepcopy(constants)
    unpublished["items"]["black_king_bar"]["dname"] = "Unpublished item"
    archive_names(settings, unpublished)
    response = await request_catalog(settings, "items")
    assert response.status_code == 200
    assert response.json() == {
        "version_id": publication.version_id,
        "items": [
            {"item_key": "black_king_bar", "name": "Black King Bar"},
            {"item_key": "power_treads", "name": "Power Treads"},
            {"item_key": "quelling_blade", "name": "Quelling Blade"},
            {"item_key": "tango", "name": "Tango"},
        ],
    }


async def test_items_without_a_display_name_do_not_get_an_invented_label(
    settings, load_opendota_fixture
):
    constants = load_opendota_fixture("constants.json")
    constants["items"]["tango"].pop("dname")
    constants["items"]["power_treads"]["dname"] = " "
    constants["items"]["bad_item"] = None
    archive_names(settings, constants)
    await publish_sample(settings, load_opendota_fixture)
    response = await request_catalog(settings, "items")
    assert response.status_code == 200
    assert response.json()["items"] == [
        {"item_key": "black_king_bar", "name": "Black King Bar"},
        {"item_key": "quelling_blade", "name": "Quelling Blade"},
    ]

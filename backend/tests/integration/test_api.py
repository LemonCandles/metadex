from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_api_uses_injected_settings_and_remains_offline(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        opendota_base_url="https://offline.example.test/api",
        data_dir=tmp_path / "data",
        duckdb_path=tmp_path / "data/metadex.duckdb",
    )
    application = create_app(settings)

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert application.state.settings is settings


def test_versioned_opendota_fixture_is_reusable(
    load_opendota_fixture: Callable[[str], Any],
) -> None:
    matches = load_opendota_fixture("public_matches_high_skill.json")

    assert isinstance(matches, list)
    assert matches
    assert all("match_id" in match for match in matches)

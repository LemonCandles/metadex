from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_ROOT, Settings

pytestmark = pytest.mark.unit


def test_defaults_are_typed_and_resolved() -> None:
    settings = Settings(_env_file=None)

    assert str(settings.opendota_base_url) == "https://api.opendota.com/api"
    assert settings.opendota_api_key is None
    assert settings.data_dir == (BACKEND_ROOT / "data").resolve()
    assert settings.duckdb_path == (BACKEND_ROOT / "data/metadex.duckdb").resolve()
    assert settings.meta_window_days == 7
    assert settings.min_sample_size == 100


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENDOTA_BASE_URL", "https://example.test/opendota")
    monkeypatch.setenv("OPENDOTA_API_KEY", "private-key")
    monkeypatch.setenv("DATA_DIR", "./custom-data")
    monkeypatch.setenv("DUCKDB_PATH", "./custom-data/catalog.duckdb")
    monkeypatch.setenv("META_WINDOW_DAYS", "14")
    monkeypatch.setenv("MIN_SAMPLE_SIZE", "250")

    settings = Settings(_env_file=None)

    assert str(settings.opendota_base_url) == "https://example.test/opendota"
    assert settings.opendota_api_key is not None
    assert settings.opendota_api_key.get_secret_value() == "private-key"
    assert settings.data_dir == (BACKEND_ROOT / "custom-data").resolve()
    assert settings.duckdb_path == (BACKEND_ROOT / "custom-data/catalog.duckdb").resolve()
    assert settings.meta_window_days == 14
    assert settings.min_sample_size == 250


def test_empty_api_key_is_treated_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENDOTA_API_KEY", "   ")

    assert Settings(_env_file=None).opendota_api_key is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("opendota_base_url", "not-a-url"),
        ("opendota_base_url", "https://user:password@example.test/api"),
        ("opendota_base_url", "https://example.test/api?api_key=leak"),
        ("duckdb_path", Path("data/catalog.sqlite")),
        ("meta_window_days", 0),
        ("meta_window_days", 366),
        ("min_sample_size", 0),
        ("cors_origins", ["*"]),
        ("cors_origins", ["http://localhost:3000/path"]),
        ("cors_origins", ["http://localhost:invalid"]),
        ("cors_origins", ["http://:3000"]),
        ("cors_origins", ["https://user:password@example.test"]),
        ("cors_origins", ["https://example.test?token=value"]),
        ("cors_origins", ["https://example.test#fragment"]),
        ("cors_origins", ["ftp://example.test"]),
    ],
)
def test_invalid_configuration_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_secret_is_hidden_in_settings_representation() -> None:
    settings = Settings(_env_file=None, opendota_api_key="do-not-print-me")

    assert "do-not-print-me" not in repr(settings)


def test_cors_environment_normalizes_and_deduplicates_origins(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://LOCALHOST:3000/", "http://localhost:3000"]')
    assert Settings(_env_file=None).cors_origins == ["http://localhost:3000"]

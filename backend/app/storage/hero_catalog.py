"""Read hero and item names from the immutable metadata of the current publication."""

import hashlib
import json
from contextlib import closing
from pathlib import Path

import duckdb

from app.analytics.catalog import PublishedHeroCatalog
from app.analytics.heroes import RepositoryUnavailable


class DuckDBHeroCatalogRepository:
    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path

    def read(self) -> PublishedHeroCatalog:
        if not self.catalog_path.is_file():
            raise RepositoryUnavailable
        try:
            with closing(duckdb.connect(str(self.catalog_path), read_only=True)) as connection:
                publication = connection.execute(
                    """SELECT v.version_id, v.manifest_path, v.manifest_json
                    FROM current_publication c JOIN dataset_versions v USING (version_id)
                    WHERE c.singleton = 1 AND v.status = 'published'"""
                ).fetchone()
            if publication is None:
                raise RepositoryUnavailable
            manifest = json.loads(publication[2])
            payload = (Path(publication[1]).parent / "metadata.json").read_bytes()
            if hashlib.sha256(payload).hexdigest() != manifest["files"]["metadata.json"]:
                raise ValueError("published metadata checksum mismatch")
            catalogs = json.loads(payload)["payloads"]
            if not isinstance(catalogs, dict):
                raise ValueError("published metadata payloads must be an object")
            heroes = catalogs.get("heroes", {})
            items = catalogs.get("items", {})
            if not isinstance(heroes, dict) or not isinstance(items, dict):
                raise ValueError("published game catalogs must be objects")
            names = {}
            for key, hero in heroes.items():
                if not isinstance(hero, dict):
                    continue
                name = hero.get("localized_name")
                if str(key).isdigit() and int(key) > 0 and isinstance(name, str) and name.strip():
                    names[int(key)] = name.strip()
            item_names = {}
            for key, item in items.items():
                if not isinstance(item, dict):
                    continue
                name = item.get("dname")
                if key.strip() and isinstance(name, str) and name.strip():
                    item_names[key] = name.strip()
            return PublishedHeroCatalog(
                version_id=publication[0], names=names, item_names=item_names
            )
        except (duckdb.Error, OSError, ValueError, KeyError, TypeError) as exc:
            raise RepositoryUnavailable from exc

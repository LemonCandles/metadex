"""Published game labels, independent of their statistical sample size."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class PublishedHeroCatalog:
    version_id: str
    names: dict[int, str]
    item_names: dict[str, str] = field(default_factory=dict)


class HeroCatalogRepository(Protocol):
    def read(self) -> PublishedHeroCatalog: ...

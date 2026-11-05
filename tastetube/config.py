"""Load taste.yaml: who we are and the facets courses are filed under."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Facet:
    id: str
    name: str
    about: str


@dataclass
class Config:
    who: str
    facets: list[Facet]
    site: Path = field(default_factory=lambda: ROOT / "site")


def load(path: str | Path | None = None) -> Config:
    path = Path(path or os.environ.get("TASTETUBE_CONFIG", ROOT / "taste.yaml"))
    taste = (yaml.safe_load(path.read_text()) or {}).get("taste", {})
    facets = [Facet(**f) for f in taste.get("facets", [])]
    ids = [f.id for f in facets]
    if len(ids) != len(set(ids)):
        raise ValueError("taste.yaml: facet ids must be unique")
    return Config(who=" ".join(str(taste.get("who", "")).split()), facets=facets)

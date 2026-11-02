"""Load taste.yaml: who we are, what we like, and the pipeline settings."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tastetube.links import extract_ids

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Facet:
    id: str
    name: str
    about: str


@dataclass
class Pipeline:
    min_own_chars: int = 100
    min_people: int = 3
    min_months: int = 3
    mentions_per_video: int = 20
    min_community_score: float = 2.0
    label_model: str = "claude-haiku-5-5"
    judge_model: str = "claude-sonnet-5-5"


@dataclass
class Config:
    who: str
    facets: list[Facet]
    avoid: list[str]
    seed_ids: list[str]
    fit_weight: dict[int, float]
    pipeline: Pipeline
    work: Path
    site: Path = field(default_factory=lambda: ROOT / "site")

    def taste_hash(self) -> str:
        """Changes when the taste changes, so the judge re-runs only then."""
        blob = json.dumps(
            {
                "who": self.who,
                "facets": [f.__dict__ for f in self.facets],
                "avoid": self.avoid,
                "seeds": self.seed_ids,
            },
            sort_keys=True,
        )
        return hashlib.sha1(blob.encode()).hexdigest()[:12]


def load(path: str | Path | None = None) -> Config:
    path = Path(path or os.environ.get("TASTETUBE_CONFIG", ROOT / "taste.yaml"))
    raw = yaml.safe_load(path.read_text())
    taste = raw.get("taste", {})
    facets = [Facet(**f) for f in taste.get("facets", [])]
    ids = [f.id for f in facets]
    if len(ids) != len(set(ids)):
        raise ValueError("taste.yaml: facet ids must be unique")
    seeds: list[str] = []
    for url in taste.get("seeds") or []:
        seeds.extend(extract_ids(str(url)) or ([url] if len(str(url)) == 11 else []))
    weights = {int(k): float(v) for k, v in (raw.get("ranking", {}).get("fit_weight") or {}).items()}
    return Config(
        who=" ".join(str(taste.get("who", "")).split()),
        facets=facets,
        avoid=list(taste.get("avoid") or []),
        seed_ids=list(dict.fromkeys(seeds)),
        fit_weight=weights or {1: 1.0, 2: 2.0, 3: 3.0},
        pipeline=Pipeline(**(raw.get("pipeline") or {})),
        work=Path(os.environ.get("TASTETUBE_WORK", ROOT / "work")),
    )

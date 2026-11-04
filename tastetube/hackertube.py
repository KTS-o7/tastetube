"""Build site/data/videos.json from HackerTube's open data plus our courses.yaml.

HackerTube (https://hackertube.org) publishes its labelled Hacker News data under ODC-By 1.0:
videos.jsonl (one card per video) and mentions.jsonl (labelled HN comments). This stage
needs no API key and spends nothing. It writes:

- the long-form library: recommended videos whose type is a talk, lecture, course,
  documentary, interview or podcast (the data has no durations, so type stands in for length)
- our courses: ordered watch paths from courses.yaml, ranked first in "Our taste"

YouTube metadata (durations, descriptions, publish dates) is not in the data and is not
written here, so nothing in the output comes from the YouTube API.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from tastetube.config import Config
from tastetube.links import excerpt

LONG_TYPES = {"talk", "lecture", "course", "documentary", "interview", "podcast"}
REC = {"strong_rec": 0, "rec": 1}  # stance -> rank, best first
MODES = {"easy", "focused", "study"}
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass
class Course:
    id: str
    title: str
    facets: list[str]
    mode: str
    why: str
    summary: str
    takeaway: str
    prereqs: str
    videos: list[str] = field(default_factory=list)


def load_courses(path: Path, facet_ids: set[str]) -> list[Course]:
    raw = yaml.safe_load(path.read_text()) or {}
    courses, seen = [], set()
    for c in raw.get("courses") or []:
        course = Course(**{k: (" ".join(v.split()) if isinstance(v, str) else v) for k, v in c.items()})
        where = f"courses.yaml: course {course.id!r}"
        if course.id in seen:
            raise ValueError(f"{where} is listed twice")
        seen.add(course.id)
        if course.mode not in MODES:
            raise ValueError(f"{where}: mode must be one of {sorted(MODES)}")
        if unknown := set(course.facets) - facet_ids:
            raise ValueError(f"{where}: unknown facets {sorted(unknown)} (see taste.yaml)")
        if bad := [v for v in course.videos if not YT_ID.match(str(v))]:
            raise ValueError(f"{where}: not YouTube video ids: {bad}")
        if len(set(course.videos)) != len(course.videos):
            raise ValueError(f"{where}: a video appears twice")
        courses.append(course)
    return courses


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _quote(m: dict) -> dict:
    return {
        "c": m["hn_comment_id"], "a": m["author"], "y": int(m["month"][:4]),
        "x": excerpt(m.get("quote") or m["text"].replace("[VIDEO]", "this video").replace("[LINK]", "a link"), 280),
        "st": m.get("story_title") or "",
    }


def _recs(mentions: list[dict]) -> dict[str, list[dict]]:
    """Recommendation mentions per video, best first: strong before plain, quoted before not."""
    out = defaultdict(list)
    for m in mentions:
        if m["stance"] in REC:
            out[m["vid"]].append(m)
    for ms in out.values():
        ms.sort(key=lambda m: (REC[m["stance"]], not m.get("quote"), m["month"]))
    return out


def _video(v: dict, recs: list[dict]) -> dict:
    years = sorted({int(m["month"][:4]) for m in recs})
    cat = v["categories"][0]["area_name"] if v.get("categories") else "Other"
    return {
        "id": v["vid"], "t": v["title"], "ch": v["channel"], "y": None, "d": 0, "e": 1,
        "s": v["score"], "mo": v["hn"]["rec_months"], "n": v["hn"]["recommenders"],
        "hy": [v["hn"]["first_year"], v["hn"]["last_year"]], "yr": years,
        "f": None, "ts": 0.0, "fa": [], "w": v.get("why_hn") or "", "su": v.get("summary") or "",
        "c": cat, "k": v["content_type"], "tk": "", "pr": "", "md": "",
        "cr": 0, "it": 0, "ls": [], "th": v["vid"], "cp": [],
        "m": [_quote(m) for m in recs[:3]],
    }


def _course(c: Course, rank: int, videos: dict[str, dict], recs: dict[str, list[dict]]) -> dict:
    lectures = [videos[vid] for vid in c.videos]
    pooled = [m for vid in c.videos for m in recs.get(vid, [])]
    months = {m["month"] for m in pooled}
    community = round(sum(v["score"] for v in lectures) / len(lectures), 1)
    # One quote per lecture from the strongest recommendations, so the course card shows breadth.
    quotes = [_quote(recs[vid][0]) for vid in c.videos if recs.get(vid)]
    quotes.sort(key=lambda q: -len(q["x"]))
    return {
        "id": "tt-" + c.id, "t": c.title, "ch": "TasteTube course", "y": None, "d": 0, "e": 1,
        "s": community, "mo": len(months), "n": len({m["author"] for m in pooled}),
        "hy": [int(min(months)[:4]), int(max(months)[:4])] if months else [],
        "yr": sorted({int(m[:4]) for m in months}),
        "f": 3, "ts": 1000.0 - rank,  # courses lead "Our taste", in courses.yaml order
        "fa": c.facets, "w": c.why, "su": c.summary, "c": "Courses", "k": "course",
        "tk": c.takeaway, "pr": c.prereqs, "md": c.mode,
        "cr": 1, "cu": 1, "it": len(lectures),
        "ls": [{"id": v["vid"], "t": v["title"], "ch": v["channel"], "d": 0} for v in lectures],
        "th": lectures[0]["vid"], "cp": [], "m": quotes[:3],
    }


def collect(data_dir: Path, courses: list[Course], cfg: Config) -> dict:
    videos = {v["vid"]: v for v in read_jsonl(data_dir / "videos.jsonl")}
    recs = _recs(read_jsonl(data_dir / "mentions.jsonl"))
    missing = [(c.id, vid) for c in courses for vid in c.videos if vid not in videos]
    if missing:
        raise ValueError(f"courses.yaml: videos not in HackerTube data: {missing}")
    in_courses = {vid for c in courses for vid in c.videos}
    library = [
        _video(v, recs.get(vid, []))
        for vid, v in videos.items()
        if vid in in_courses
        or (v["hn"]["recommenders"] > 0 and v["shelf_life"] != "news" and v["content_type"] in LONG_TYPES)
    ]
    items = [_course(c, i, videos, recs) for i, c in enumerate(courses)] + library
    items.sort(key=lambda v: (-v["ts"], -v["s"], v["id"]))
    return {
        "meta": {
            "generated": date.today().isoformat(),
            "demo": False,
            "source": "hackertube",
            "durations": False,
            "min_minutes": cfg.pipeline.min_minutes,
            "facets": [{"id": f.id, "name": f.name, "about": f.about} for f in cfg.facets],
            "counts": {
                "videos": len(library),
                "courses": len(courses),
                "judged": len(courses),
                "ours": len(courses),
                "comments": sum(len(ms) for ms in recs.values()),
            },
        },
        "videos": items,
    }


def run(data_dir: Path, cfg: Config, courses_path: Path, out: Path) -> Path:
    if not (data_dir / "videos.jsonl").exists():
        raise SystemExit(f"{data_dir}/videos.jsonl not found. Download https://hackertube.org/data and unzip it.")
    courses = load_courses(courses_path, {f.id for f in cfg.facets})
    data = collect(data_dir, courses, cfg)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    c = data["meta"]["counts"]
    size = math.ceil(out.stat().st_size / 1024)
    print(f"hackertube: {c['courses']} courses, {c['videos']:,} library videos -> {out} ({size:,} KB)")
    return out

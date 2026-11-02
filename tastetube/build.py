"""Stage 5: write site/data/videos.json, the only file the static site reads."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from tastetube.config import Config
from tastetube.judge import LABEL_RANK, lectures
from tastetube.links import excerpt, is_course, own_text, parse_chapters
from tastetube.rank import taste_score


def _year(ts: int | None) -> int | None:
    return datetime.fromtimestamp(ts, timezone.utc).year if ts else None


def collect(con: sqlite3.Connection, cfg: Config) -> dict:
    taste = cfg.taste_hash()
    rows = con.execute(
        """
        SELECT y.video_id, y.title, y.channel, y.published, y.duration, y.embeddable, y.description,
               y.items, s.community, s.rec_months, s.rec_people, cd.first_ts, cd.last_ts,
               j.fit, j.facets, j.why, j.summary, j.category, j.kind, j.takeaway, j.prereqs, j.mode
        FROM scores s
        JOIN yt y ON y.video_id = s.video_id AND y.available = 1
        JOIN candidates cd ON cd.video_id = s.video_id
        LEFT JOIN judgments j ON j.video_id = s.video_id AND j.taste = ?
        WHERE s.community >= ? AND y.duration >= ?
        """,
        (taste, cfg.pipeline.min_community_score, cfg.pipeline.min_minutes * 60),
    ).fetchall()
    ments = defaultdict(list)
    for vid, label, cid, author, ts, story_id, story, text in con.execute(
        """
        SELECT l.video_id, l.label, c.id, c.author, c.ts, c.story_id, c.story_title, c.text
        FROM labels l JOIN comments c ON c.id = l.comment_id
        WHERE l.label IN ('strong_recommendation', 'recommendation')
        """
    ):
        ments[vid].append((LABEL_RANK[label], ts, {
            "c": cid, "a": author, "y": _year(ts), "x": excerpt(own_text(text), 280),
            "st": story, "s": story_id,
        }))
    videos = []
    for (vid, title, channel, published, duration, embeddable, desc, items, community, rec_months,
         rec_people, first_ts, last_ts, fit, facets, why, summary, category, kind, takeaway, prereqs,
         mode) in rows:
        course = is_course(vid)
        ls = [{"id": i, "t": t, "d": d} for i, t, d in lectures(con, vid)] if course else []
        best = [m for _, _, m in sorted(ments[vid], key=lambda m: (m[0], -len(m[2]["x"])))[:3]]
        years = sorted({m["y"] for _, _, m in ments[vid] if m["y"]})
        videos.append({
            "id": vid, "t": title, "ch": channel, "y": int(published[:4]) if published else None,
            "d": duration, "e": embeddable, "s": community, "mo": rec_months, "n": rec_people,
            "hy": [_year(first_ts), _year(last_ts)], "yr": years,
            "f": fit, "ts": taste_score(community, fit, cfg.fit_weight),
            "fa": json.loads(facets) if facets else [], "w": why or "", "su": summary or "",
            "c": category or "Other", "k": "course" if course else (kind or "other"), "m": best,
            "tk": takeaway or "", "pr": prereqs or "", "md": mode or "",
            "cr": int(course), "it": items or 0, "ls": ls,
            "th": ls[0]["id"] if ls else vid,
            "cp": [] if course else [[sec, t] for sec, t in parse_chapters(desc)],
        })
    videos.sort(key=lambda v: (-v["ts"], -v["s"], v["id"]))
    judged = sum(v["f"] is not None for v in videos)
    return {
        "meta": {
            "generated": date.today().isoformat(),
            "demo": False,
            "min_minutes": cfg.pipeline.min_minutes,
            "facets": [{"id": f.id, "name": f.name, "about": f.about} for f in cfg.facets],
            "counts": {
                "videos": len(videos),
                "courses": sum(v["cr"] for v in videos),
                "judged": judged,
                "ours": sum(1 for v in videos if v["f"]),
                "comments": con.execute("SELECT COUNT(*) FROM comments").fetchone()[0],
            },
        },
        "videos": videos,
    }


def run(con: sqlite3.Connection, cfg: Config, out: Path | None = None) -> Path:
    data = collect(con, cfg)
    out = out or cfg.site / "data" / "videos.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    c = data["meta"]["counts"]
    print(f"build: {c['videos']:,} videos ({c['ours']:,} in our taste) -> {out} "
          f"({out.stat().st_size / 1e6:.1f} MB)")
    return out

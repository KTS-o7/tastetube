"""Stage 4: judge each well-loved video against OUR taste, and write its card.

One call per video. The system prompt holds the whole taste profile and is
cached, so each call pays full price only for the short video description.
Results are keyed by the taste hash: edit taste.yaml and only the judge re-runs.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

from tastetube.config import Config
from tastetube.links import excerpt, own_text
from tastetube.llm import Job, Runner, make_key

CATEGORIES = [
    "AI & Machine Learning", "Programming", "Systems & Infrastructure", "Security",
    "Computer Science", "Hardware & Electronics", "Math", "Physics & Space",
    "Biology & Medicine", "Chemistry & Materials", "Engineering", "History",
    "Economics & Finance", "Startups & Business", "Design & UX", "Politics & Society",
    "Philosophy & Psychology", "Education & Learning", "Music", "Film & Art", "Games",
    "Comedy & Entertainment", "Other",
]
KINDS = [
    "lecture", "talk", "explainer", "documentary", "tutorial", "demo", "interview",
    "music", "entertainment", "other",
]
LABEL_RANK = {"strong_recommendation": 0, "recommendation": 1, "neutral": 2, "criticism": 3, "joke": 4}


def schema(cfg: Config) -> dict:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "What the video is. Plain words, at most 25 words."},
            "why": {"type": "string", "description": "Why WE would watch it, at most 20 words. Empty if fit is 0."},
            "facets": {"type": "array", "items": {"type": "string", "enum": [f.id for f in cfg.facets]},
                       "description": "Our facets it belongs to, at most 3. Empty if fit is 0."},
            "fit": {"type": "integer", "enum": [0, 1, 2, 3]},
            "category": {"type": "string", "enum": CATEGORIES},
            "kind": {"type": "string", "enum": KINDS},
        },
        "required": ["summary", "why", "facets", "fit", "category", "kind"],
        "additionalProperties": False,
    }


def system_prompt(cfg: Config, seed_titles: list[str]) -> str:
    facets = "\n".join(f"- {f.id}: {f.name}. {f.about}" for f in cfg.facets)
    avoid = "\n".join(f"- {a}" for a in cfg.avoid) or "- (nothing listed)"
    seeds = "\n".join(f"- {t}" for t in seed_titles) or "- (none yet)"
    return f"""You curate a personal video library. The candidates are YouTube videos that
Hacker News commenters kept recommending between 2007 and today. Judge each video
against OUR taste, then write a short card for it.

## Who we are
{cfg.who}

## Our facets
{facets}

## We avoid
{avoid}

## Videos we already love (taste anchors)
{seeds}

## How to score fit
3 = core: squarely inside a facet and high-signal. We would clear an evening for it.
2 = strong: clearly inside a facet and worth watching.
1 = adjacent: touches a facet, or a broadly excellent watch for a curious engineer.
0 = outside our taste, or it matches something we avoid.

Be strict. HN loves many videos that are not for us; most candidates should get 0 or 1.
Judge the video itself. Use the HN comments as evidence of quality, not of topic.
A famous talk is not core just because it is famous.

## Card rules
- summary: say what the video is and who made it, in plain words. No hype words.
- why: speak to us directly ("Shows how...", "Best explanation of..."). Tie it to a facet.
  Do not repeat the summary. Empty string when fit is 0.
- facets: ids from the list above, best match first, at most 3. Empty when fit is 0.
- category: the broad topic, for people browsing the whole library.
- kind: the format of the video.
"""


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds or 0, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def gather(con: sqlite3.Connection, cfg: Config) -> list[dict]:
    """Collect what the judge sees for each video above the community threshold."""
    vids = con.execute(
        """
        SELECT y.video_id, y.title, y.channel, y.published, y.duration, y.description, s.community
        FROM scores s JOIN yt y ON y.video_id = s.video_id
        WHERE y.available = 1 AND s.community >= ?
        ORDER BY s.community DESC
        """,
        (cfg.pipeline.min_community_score,),
    ).fetchall()
    ments = defaultdict(list)
    for vid, label, story, text in con.execute(
        """
        SELECT l.video_id, l.label, c.story_title, c.text
        FROM labels l JOIN comments c ON c.id = l.comment_id
        """
    ):
        ments[vid].append((LABEL_RANK.get(label, 9), story, own_text(text)))
    out = []
    for vid, title, channel, published, duration, desc, community in vids:
        ms = sorted(ments[vid], key=lambda m: (m[0], -len(m[2])))
        stories = list(dict.fromkeys(s for _, s, _ in ms if s))[:5]
        quotes = [excerpt(t, 300) for rank, _, t in ms if rank <= 1][:3]
        out.append(dict(video_id=vid, title=title, channel=channel, year=(published or "")[:4],
                        duration=duration, description=desc or "", stories=stories, quotes=quotes,
                        community=community))
    return out


def render(v: dict) -> str:
    desc = " ".join((v["description"] or "").split())[:700]
    stories = "; ".join(f'"{s}"' for s in v["stories"]) or "(unknown)"
    quotes = "\n".join(f"- {q}" for q in v["quotes"]) or "- (no direct quotes)"
    return (
        f"Video: \"{v['title']}\" by {v['channel']} ({v['year']}, {_fmt_duration(v['duration'])})\n"
        f"YouTube description: {desc or '(empty)'}\n"
        f"HN threads where it came up: {stories}\n"
        f"What HN commenters said:\n{quotes}"
    )


def run(con: sqlite3.Connection, cfg: Config, runner: Runner, mode: str = "batch",
        limit: int | None = None, confirm: bool = True) -> None:
    model = cfg.pipeline.judge_model
    seeds = []
    if cfg.seed_ids:
        q = f"SELECT title, channel FROM yt WHERE available = 1 AND video_id IN ({','.join('?' * len(cfg.seed_ids))})"
        seeds = [f'"{t}" by {c}' for t, c in con.execute(q, cfg.seed_ids)]
    system = system_prompt(cfg, seeds)
    videos = gather(con, cfg)
    if limit:
        videos = videos[:limit]
    jobs = []
    for v in videos:
        user = render(v)
        jobs.append(Job(make_key("judge", model, system, user), user))
    results = runner.run("judge", model, system, jobs, schema(cfg), max_tokens=300, mode=mode, confirm=confirm)
    taste = cfg.taste_hash()
    rows = []
    for v, j in zip(videos, jobs):
        r = results.get(j.key)
        if not r:
            continue
        fit = int(r["fit"])
        facets = r["facets"][:3] if fit else []
        rows.append((v["video_id"], taste, fit, json.dumps(facets), r["why"] if fit else "",
                     r["summary"], r["category"], r["kind"]))
    con.executemany("INSERT OR REPLACE INTO judgments VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    fits = defaultdict(int)
    for row in rows:
        fits[row[2]] += 1
    n, tin, tout = runner.usage("judge")
    print(f"judge: {len(rows):,}/{len(jobs):,} videos judged; fit 3/2/1/0 = "
          f"{fits[3]}/{fits[2]}/{fits[1]}/{fits[0]} (all-time tokens: {tin:,} in, {tout:,} out)")

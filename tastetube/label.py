"""Stage 3: label each kept mention. Is the commenter recommending the video?

This is a simple classification, so it runs on Haiku. The system prompt is
longer than 512 tokens on purpose (few-shot examples), so prompt caching applies.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from tastetube.config import Config
from tastetube.links import clean_text, is_course
from tastetube.llm import Job, Runner, make_key

LABELS = ["strong_recommendation", "recommendation", "neutral", "joke", "criticism"]

SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": LABELS}},
    "required": ["label"],
    "additionalProperties": False,
}

SYSTEM = """You label Hacker News comments that link to YouTube.
Decide what the commenter does with ONE target. Answer with one label.
The target is either a single video or a course (a YouTube playlist of lectures).
For a course, judge what the commenter says about the course or series as a whole.

Labels:
- strong_recommendation: the commenter is enthusiastic and pushes people to watch it.
  Signals: "must watch", "best talk I have seen on X", "changed how I think", "watch this, seriously".
- recommendation: the commenter suggests the video as worth watching or as a good way to learn something.
  Signals: "good intro to this", "this talk covers it well", "I recommend", a link given as the answer to "how do I learn X".
- neutral: the video is cited as a source, evidence, or a reference, or it is mentioned without endorsing it.
  Signals: "here is the clip where he says it", "source:", "the talk is at <link>", a link in a list of facts.
- joke: humour, sarcasm, memes, a rickroll, or a music link used as a punchline.
- criticism: the commenter says the video is wrong, misleading, low quality, or warns people away from it.

Rules:
- A comment can link several videos. Judge only the target video. If the target is one item in a list
  of recommended videos, label it recommendation.
- Use the story title only as context for the discussion.
- Quoting or linking a video to disagree with the person in the video is neutral, unless the commenter
  also criticises the video itself.
- When you are unsure between recommendation and neutral, choose neutral.
- When you are unsure between recommendation and strong_recommendation, choose recommendation.

Examples:
1. Comment: "If you want to understand how transformers work, this lecture builds one from scratch in two hours. Best resource I know of, I rewatch it every year: <link>"
   -> strong_recommendation
2. Comment: "There's a decent talk from the Postgres folks on exactly this lock contention issue: <link> The second half is the relevant part."
   -> recommendation
3. Comment: "He said this on stage, it's at 14:20 here: <link> so the claim in the article is not new."
   -> neutral
4. Comment: "Obligatory: <link>" (target video title: "Never Gonna Give You Up")
   -> joke
5. Comment: "Please don't learn from that video, half of what it says about memory ordering is wrong. Read the C++ standard papers instead."
   -> criticism
"""


def render(story_title: str | None, video_id: str, yt_title: str | None, channel: str | None,
           author: str, ts: int, text: str, items: int = 0) -> str:
    month = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")
    body = clean_text(text)[:1500]
    target = f"course (playlist, {items} lectures)" if is_course(video_id) else "video"
    return (
        f"Story title: {story_title or '(unknown)'}\n"
        f"Target {target}: {video_id} - \"{yt_title or '?'}\" by {channel or '?'}\n"
        f"Comment by {author} ({month}):\n\"\"\"\n{body}\n\"\"\""
    )


def run(con: sqlite3.Connection, cfg: Config, runner: Runner, mode: str = "batch",
        limit: int | None = None, confirm: bool = True) -> None:
    model = cfg.pipeline.label_model
    rows = con.execute(
        """
        SELECT k.comment_id, k.video_id, c.story_title, y.title, y.channel, c.author, c.ts, c.text, y.items
        FROM kept k
        JOIN comments c ON c.id = k.comment_id
        JOIN yt y ON y.video_id = k.video_id AND y.available = 1
        WHERE y.duration >= ?   -- the long-form gate: short videos never cost an LLM call
        ORDER BY k.video_id, c.ts
        """,
        (cfg.pipeline.min_minutes * 60,),
    ).fetchall()
    if limit:
        rows = rows[:limit]
    jobs, ids = [], []
    for cid, vid, story, title, channel, author, ts, text, items in rows:
        user = render(story, vid, title, channel, author, ts, text, items or 0)
        jobs.append(Job(make_key("label", model, SYSTEM, user), user))
        ids.append((cid, vid))
    results = runner.run("label", model, SYSTEM, jobs, SCHEMA, max_tokens=32, mode=mode, confirm=confirm)
    out = [(cid, vid, results[j.key]["label"]) for (cid, vid), j in zip(ids, jobs) if j.key in results]
    con.executemany("INSERT OR REPLACE INTO labels VALUES (?,?,?)", out)
    con.commit()
    n, tin, tout = runner.usage("label")
    print(f"label: {len(out):,}/{len(jobs):,} mentions labelled (all-time tokens: {tin:,} in, {tout:,} out)")

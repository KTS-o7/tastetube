"""One SQLite file holds every stage's output, so each stage can re-run alone.

Caches (YouTube metadata, LLM results) survive re-runs. Re-running `extract`
rebuilds the mention tables but never throws away paid-for LLM results.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY, author TEXT, ts INTEGER, month TEXT, parent INTEGER,
    text TEXT, own_len INTEGER, story_id INTEGER, story_title TEXT
);
CREATE TABLE IF NOT EXISTS mentions (
    comment_id INTEGER, video_id TEXT, PRIMARY KEY (comment_id, video_id)
);
CREATE INDEX IF NOT EXISTS mentions_video ON mentions(video_id);
-- Videos that pass the people/months gate.
CREATE TABLE IF NOT EXISTS candidates (
    video_id TEXT PRIMARY KEY, people INTEGER, months INTEGER, first_ts INTEGER, last_ts INTEGER
);
-- The sample of mentions (up to N per video) that the labeler reads.
CREATE TABLE IF NOT EXISTS kept (
    comment_id INTEGER, video_id TEXT, PRIMARY KEY (comment_id, video_id)
);
CREATE TABLE IF NOT EXISTS yt (
    video_id TEXT PRIMARY KEY, available INTEGER, title TEXT, channel TEXT,
    published TEXT, description TEXT, duration INTEGER, embeddable INTEGER,
    views INTEGER, fetched_at INTEGER
);
CREATE TABLE IF NOT EXISTS labels (
    comment_id INTEGER, video_id TEXT, label TEXT, PRIMARY KEY (comment_id, video_id)
);
CREATE TABLE IF NOT EXISTS scores (
    video_id TEXT PRIMARY KEY, community REAL, rec_months INTEGER,
    strong_months INTEGER, rec_people INTEGER
);
CREATE TABLE IF NOT EXISTS judgments (
    video_id TEXT, taste TEXT, fit INTEGER, facets TEXT, why TEXT,
    summary TEXT, category TEXT, kind TEXT, PRIMARY KEY (video_id, taste)
);
-- Every LLM answer, keyed by a hash of (model, prompt, input).
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY, kind TEXT, result TEXT, in_tokens INTEGER, out_tokens INTEGER
);
-- Batches we sent and have not read back yet. Lets a crashed run resume.
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY, kind TEXT, n INTEGER, created_at INTEGER
);
"""


def connect(work: Path) -> sqlite3.Connection:
    work.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(work / "tastetube.db")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con

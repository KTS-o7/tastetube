"""Scores.

community score (HackerTube's formula):
    distinct months with a recommendation + 0.5 x distinct months with a strong one.
    Counting months, not comments, stops one hot thread from inflating a video.

taste score (ours):
    fit_weight[fit] x log2(1 + community)
    The log squashes popularity, so a fit-3 video with a small but real HN
    following beats a fit-1 video that HN posts every week.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from collections.abc import Iterable

REC = {"recommendation", "strong_recommendation"}


def community_score(mentions: Iterable[tuple[str, str]]) -> tuple[float, int, int]:
    """mentions: (month, label) pairs. Returns (score, rec_months, strong_months)."""
    rec, strong = set(), set()
    for month, label in mentions:
        if label in REC:
            rec.add(month)
        if label == "strong_recommendation":
            strong.add(month)
    return len(rec) + 0.5 * len(strong), len(rec), len(strong)


def taste_score(community: float, fit: int | None, weights: dict[int, float]) -> float:
    if not fit:
        return 0.0
    return round(weights.get(fit, 0.0) * math.log2(1 + community), 4)


def run(con: sqlite3.Connection) -> int:
    rows = con.execute(
        """
        SELECT l.video_id, c.month, c.author, l.label
        FROM labels l
        JOIN comments c ON c.id = l.comment_id
        JOIN yt y ON y.video_id = l.video_id AND y.available = 1
        """
    ).fetchall()
    by_video: dict[str, list] = defaultdict(list)
    people: dict[str, set] = defaultdict(set)
    for vid, month, author, label in rows:
        by_video[vid].append((month, label))
        if label in REC:
            people[vid].add(author)
    con.execute("DELETE FROM scores")
    con.executemany(
        "INSERT INTO scores VALUES (?,?,?,?,?)",
        [(vid, *community_score(m), len(people[vid])) for vid, m in by_video.items()],
    )
    con.commit()
    return len(by_video)

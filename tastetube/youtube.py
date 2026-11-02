"""Stage 2: fetch YouTube metadata for candidates (and seeds).

Uses the YouTube Data API v3 `videos.list`: 50 IDs per call, 1 quota unit per
call. 10,000 candidates cost about 200 units of the free 10,000/day quota.
A video missing from the response is deleted or private; we mark it unavailable
so no LLM money is spent on it.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time

import requests

API = "https://www.googleapis.com/youtube/v3/videos"
_DUR = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_duration(iso: str | None) -> int:
    """ISO 8601 duration ('PT1H2M3S') to seconds. Live streams report 'P0D'."""
    m = _DUR.fullmatch(iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def parse_item(item: dict) -> tuple:
    sn, cd, st = item.get("snippet", {}), item.get("contentDetails", {}), item.get("status", {})
    stats = item.get("statistics", {})
    playable = st.get("privacyStatus") in ("public", "unlisted") and st.get("uploadStatus", "processed") == "processed"
    return (
        item["id"],
        int(playable),
        sn.get("title"),
        sn.get("channelTitle"),
        sn.get("publishedAt"),
        (sn.get("description") or "")[:2000],
        parse_duration(cd.get("duration")),
        int(bool(st.get("embeddable", True))),
        int(stats.get("viewCount", 0) or 0),
        int(time.time()),
    )


def fetch(ids: list[str], key: str, session: requests.Session | None = None) -> list[tuple]:
    """Fetch up to 50 IDs. IDs missing from the reply become 'unavailable' rows."""
    s = session or requests.Session()
    for attempt in range(5):
        r = s.get(
            API,
            params={"part": "snippet,contentDetails,status,statistics", "id": ",".join(ids), "key": key},
            timeout=30,
        )
        if r.status_code in (429, 500, 502, 503):
            time.sleep(2**attempt)
            continue
        if r.status_code == 403:
            raise SystemExit(f"YouTube API refused the request (quota or key): {r.text[:300]}")
        r.raise_for_status()
        break
    else:
        r.raise_for_status()
    rows = [parse_item(it) for it in r.json().get("items", [])]
    found = {row[0] for row in rows}
    now = int(time.time())
    rows += [(vid, 0, None, None, None, None, 0, 0, 0, now) for vid in ids if vid not in found]
    return rows


def run(con: sqlite3.Connection, extra_ids: list[str] | None = None) -> None:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise SystemExit("Set YOUTUBE_API_KEY (Google Cloud console -> YouTube Data API v3 -> API key).")
    want = [r[0] for r in con.execute(
        "SELECT video_id FROM candidates WHERE video_id NOT IN (SELECT video_id FROM yt)"
    )]
    have = {r[0] for r in con.execute("SELECT video_id FROM yt")}
    want += [v for v in (extra_ids or []) if v not in have and v not in want]
    if not want:
        print("meta: nothing new to fetch")
        return
    session = requests.Session()
    for i in range(0, len(want), 50):
        rows = fetch(want[i : i + 50], key, session)
        con.executemany("INSERT OR REPLACE INTO yt VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        print(f"\rmeta: {min(i + 50, len(want)):,}/{len(want):,}", end="", flush=True)
    gone = con.execute("SELECT COUNT(*) FROM yt WHERE available = 0").fetchone()[0]
    print(f"\nmeta: done; {gone:,} videos are deleted or private and will be skipped")

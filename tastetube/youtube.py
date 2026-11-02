"""Stage 2: fetch YouTube metadata for candidate videos, candidate courses, and seeds.

YouTube Data API v3. Every list call takes up to 50 IDs and costs 1 quota unit
(free quota: 10,000 units a day).
- Videos: `videos.list`. A video missing from the reply is deleted or private.
- Courses: `playlists.list`, then `playlistItems.list` for the lecture IDs, then
  `videos.list` for each lecture's length. A course's duration is the sum.
Unavailable items are marked so that no LLM money is spent on them.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time

import requests

from tastetube.links import is_course

API = "https://www.googleapis.com/youtube/v3"
MAX_LECTURES = 300
_DUR = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_duration(iso: str | None) -> int:
    """ISO 8601 duration ('PT1H2M3S') to seconds. Live streams report 'P0D'."""
    m = _DUR.fullmatch(iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _row(item_id, available, title=None, channel=None, published=None, description=None,
         duration=0, embeddable=0, views=0, items=0) -> tuple:
    return (item_id, int(available), title, channel, published, (description or "")[:2000],
            duration, int(embeddable), views, items, int(time.time()))


def parse_video(item: dict) -> tuple:
    sn, cd, st = item.get("snippet", {}), item.get("contentDetails", {}), item.get("status", {})
    playable = st.get("privacyStatus") in ("public", "unlisted") and st.get("uploadStatus", "processed") == "processed"
    return _row(item["id"], playable, sn.get("title"), sn.get("channelTitle"), sn.get("publishedAt"),
                sn.get("description"), parse_duration(cd.get("duration")), st.get("embeddable", True),
                int(item.get("statistics", {}).get("viewCount", 0) or 0))


class Client:
    def __init__(self, key: str, session: requests.Session | None = None):
        self.key = key
        self.s = session or requests.Session()

    def get(self, path: str, **params) -> dict:
        for attempt in range(5):
            r = self.s.get(f"{API}/{path}", params={**params, "key": self.key}, timeout=30)
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2**attempt)
                continue
            if r.status_code == 403:
                raise SystemExit(f"YouTube API refused the request (quota or key): {r.text[:300]}")
            if r.status_code == 404:
                return {"items": []}
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    def videos(self, ids: list[str]) -> list[tuple]:
        """Rows for up to 50 video IDs; missing IDs become 'unavailable' rows."""
        data = self.get("videos", part="snippet,contentDetails,status,statistics", id=",".join(ids))
        rows = [parse_video(it) for it in data.get("items", [])]
        found = {r[0] for r in rows}
        return rows + [_row(v, 0) for v in ids if v not in found]

    def playlists(self, ids: list[str]) -> dict[str, dict]:
        data = self.get("playlists", part="snippet,contentDetails,status", id=",".join(ids), maxResults=50)
        return {it["id"]: it for it in data.get("items", [])}

    def lecture_ids(self, playlist_id: str) -> list[str]:
        out, token = [], None
        while len(out) < MAX_LECTURES:
            data = self.get("playlistItems", part="contentDetails", playlistId=playlist_id,
                            maxResults=50, **({"pageToken": token} if token else {}))
            out += [it["contentDetails"]["videoId"] for it in data.get("items", [])]
            token = data.get("nextPageToken")
            if not token:
                break
        return list(dict.fromkeys(out))[:MAX_LECTURES]


def _store_videos(con, client: Client, ids: list[str]) -> None:
    for i in range(0, len(ids), 50):
        con.executemany("INSERT OR REPLACE INTO yt VALUES (?,?,?,?,?,?,?,?,?,?,?)", client.videos(ids[i : i + 50]))
    con.commit()


def store_course(con, course_id: str, meta: dict | None, lectures: list[str]) -> None:
    """Write the course row. Its length is the sum of its playable lectures."""
    con.execute("DELETE FROM course_items WHERE course_id = ?", (course_id,))
    if meta is None or meta.get("status", {}).get("privacyStatus") not in ("public", "unlisted"):
        con.execute("INSERT OR REPLACE INTO yt VALUES (?,?,?,?,?,?,?,?,?,?,?)", _row(course_id, 0))
        return
    con.executemany("INSERT INTO course_items VALUES (?,?,?)", [(course_id, i, v) for i, v in enumerate(lectures)])
    ok = con.execute(
        f"SELECT COUNT(*), COALESCE(SUM(duration), 0) FROM yt WHERE available = 1 AND video_id IN "
        f"(SELECT video_id FROM course_items WHERE course_id = ?)",
        (course_id,),
    ).fetchone()
    sn = meta.get("snippet", {})
    con.execute("INSERT OR REPLACE INTO yt VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                _row(course_id, ok[0] > 0, sn.get("title"), sn.get("channelTitle"), sn.get("publishedAt"),
                     sn.get("description"), ok[1], 1, 0, ok[0]))


def run(con: sqlite3.Connection, extra_ids: list[str] | None = None, client: Client | None = None) -> None:
    if client is None:
        key = os.environ.get("YOUTUBE_API_KEY")
        if not key:
            raise SystemExit("Set YOUTUBE_API_KEY (Google Cloud console -> YouTube Data API v3 -> API key).")
        client = Client(key)
    have = {r[0] for r in con.execute("SELECT video_id FROM yt")}
    want = [r[0] for r in con.execute("SELECT video_id FROM candidates")] + list(extra_ids or [])
    want = [i for i in dict.fromkeys(want) if i not in have]
    videos = [i for i in want if not is_course(i)]
    courses = [i for i in want if is_course(i)]
    if not want:
        print("meta: nothing new to fetch")
        return
    _store_videos(con, client, videos)
    print(f"meta: {len(videos):,} videos fetched")
    for i in range(0, len(courses), 50):
        part = courses[i : i + 50]
        metas = client.playlists(part)
        for cid in part:
            lectures = client.lecture_ids(cid) if cid in metas else []
            known = {r[0] for r in con.execute("SELECT video_id FROM yt")}
            _store_videos(con, client, [v for v in lectures if v not in known])
            store_course(con, cid, metas.get(cid), lectures)
        con.commit()
        print(f"meta: {min(i + 50, len(courses)):,}/{len(courses):,} courses fetched")
    gone = con.execute(
        "SELECT COUNT(*) FROM yt WHERE available = 0 AND video_id IN (SELECT video_id FROM candidates)"
    ).fetchone()[0]
    print(f"meta: done; {gone:,} candidates are deleted or private and will be skipped")

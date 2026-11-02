"""Stage 1: find every HN comment that links a YouTube video, and pick candidates.

DuckDB does the two heavy jobs on the 12 GB Parquet archive:
  1. scan 43M comments for the substring 'youtu', and
  2. walk each kept comment up its parent chain to the root story (for the title).
Everything else is plain Python + SQLite, so it is easy to test.
"""

from __future__ import annotations

import csv
import sqlite3
import tempfile
import time
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from tastetube.config import Config
from tastetube.links import extract_ids, own_text

MAX_DEPTH = 1000  # the deepest HN threads are a few hundred levels


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def parquet_glob(cfg: Config) -> str:
    return str(cfg.work / "hn" / "data" / "*" / "*.parquet")


def scan_youtube_comments(glob: str) -> Iterator[tuple]:
    """Yield (id, author, unix_ts, parent, html) for live comments that mention 'youtu'."""
    import duckdb

    con = duckdb.connect()
    cur = con.execute(
        f"""
        SELECT "id", "by", CAST(epoch("time") AS BIGINT), "parent", "text"
        FROM read_parquet({_lit(glob)})
        WHERE "type" = 2
          AND coalesce("deleted", 0) = 0 AND coalesce("dead", 0) = 0
          AND "text" ILIKE '%youtu%'
        """
    )
    while rows := cur.fetchmany(20_000):
        yield from rows


def ingest(con: sqlite3.Connection, rows: Iterable[tuple]) -> int:
    """Store comments that contain at least one YouTube video ID."""
    con.execute("DELETE FROM comments")
    con.execute("DELETE FROM mentions")
    n = 0
    batch_c, batch_m = [], []
    for cid, author, ts, parent, raw in rows:
        ids = extract_ids(raw)
        if not ids:
            continue
        month = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")
        batch_c.append((cid, author, ts, month, parent, raw, len(own_text(raw))))
        batch_m.extend((cid, vid) for vid in ids)
        n += 1
        if len(batch_c) >= 10_000:
            _flush(con, batch_c, batch_m)
    _flush(con, batch_c, batch_m)
    con.commit()
    return n


def _flush(con, batch_c, batch_m):
    con.executemany(
        "INSERT OR REPLACE INTO comments (id, author, ts, month, parent, text, own_len)"
        " VALUES (?,?,?,?,?,?,?)",
        batch_c,
    )
    con.executemany("INSERT OR IGNORE INTO mentions VALUES (?,?)", batch_m)
    batch_c.clear()
    batch_m.clear()


def select_candidates(con: sqlite3.Connection, cfg: Config) -> tuple[int, int]:
    """Apply the quality gate, then keep up to N mentions per video, spread over people."""
    p = cfg.pipeline
    con.execute("DELETE FROM candidates")
    con.execute("DELETE FROM kept")
    con.execute(
        """
        INSERT INTO candidates
        SELECT m.video_id, COUNT(DISTINCT c.author), COUNT(DISTINCT c.month), MIN(c.ts), MAX(c.ts)
        FROM mentions m JOIN comments c ON c.id = m.comment_id
        WHERE c.own_len >= ? AND c.author IS NOT NULL
        GROUP BY m.video_id
        HAVING COUNT(DISTINCT c.author) >= ? AND COUNT(DISTINCT c.month) >= ?
        """,
        (p.min_own_chars, p.min_people, p.min_months),
    )
    # First pick each person's earliest mention, then their second, and so on.
    con.execute(
        """
        INSERT INTO kept
        WITH m AS (
            SELECT m.video_id, c.id AS comment_id, c.ts,
                   ROW_NUMBER() OVER (PARTITION BY m.video_id, c.author ORDER BY c.ts) AS turn
            FROM mentions m
            JOIN comments c ON c.id = m.comment_id
            JOIN candidates v ON v.video_id = m.video_id
            WHERE c.own_len >= ? AND c.author IS NOT NULL
        ), r AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY turn, ts) AS rn FROM m
        )
        SELECT comment_id, video_id FROM r WHERE rn <= ?
        """,
        (p.min_own_chars, p.mentions_per_video),
    )
    con.commit()
    videos = con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    kept = con.execute("SELECT COUNT(*) FROM kept").fetchone()[0]
    return videos, kept


def resolve_roots(glob: str, pairs: list[tuple[int, int]]) -> dict[int, tuple[int, str | None]]:
    """Map comment id -> (root story id, story title), walking parent links in DuckDB.

    `pairs` is [(comment_id, parent_id)]. Each loop step moves every unfinished
    comment one level up. A node that is not itself a comment is the root.
    """
    import duckdb

    con = duckdb.connect()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "walk.csv"
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["cid", "node"])
            w.writerows(pairs)
        con.execute(
            f"""CREATE TEMP TABLE walk AS SELECT * FROM read_csv({_lit(str(path))},
                header = true, columns = {{'cid': 'UBIGINT', 'node': 'UBIGINT'}})"""
        )
    con.execute(
        f"""CREATE TEMP TABLE cp AS SELECT "id" AS id, "parent" AS up
            FROM read_parquet({_lit(glob)}) WHERE "type" = 2"""
    )
    con.execute("CREATE TEMP TABLE done (cid UBIGINT, node UBIGINT)")
    for _ in range(MAX_DEPTH):
        con.execute(
            "CREATE OR REPLACE TEMP TABLE step AS "
            "SELECT w.cid, w.node, cp.up FROM walk w LEFT JOIN cp ON cp.id = w.node"
        )
        con.execute("INSERT INTO done SELECT cid, node FROM step WHERE up IS NULL")
        con.execute("CREATE OR REPLACE TEMP TABLE walk AS SELECT cid, up AS node FROM step WHERE up IS NOT NULL")
        if con.execute("SELECT COUNT(*) FROM walk").fetchone()[0] == 0:
            break
    rows = con.execute(
        f"""
        SELECT d.cid, d.node, s.title
        FROM done d
        LEFT JOIN (SELECT "id" AS id, "title" AS title FROM read_parquet({_lit(glob)})
                   WHERE "type" IN (1, 3)) s ON s.id = d.node
        """
    ).fetchall()
    return {int(cid): (int(node) if node is not None else None, title) for cid, node, title in rows}


def store_roots(con: sqlite3.Connection, roots: dict[int, tuple[int, str | None]]) -> None:
    con.executemany(
        "UPDATE comments SET story_id = ?, story_title = ? WHERE id = ?",
        [(sid, title, cid) for cid, (sid, title) in roots.items()],
    )
    con.commit()


def run(con: sqlite3.Connection, cfg: Config) -> None:
    glob = parquet_glob(cfg)
    if not list((cfg.work / "hn" / "data").glob("*/*.parquet")):
        raise SystemExit(f"No Parquet files under {cfg.work / 'hn'}. Run `tastetube download` first.")
    t = time.time()
    n = ingest(con, scan_youtube_comments(glob))
    print(f"extract: {n:,} comments link a YouTube video ({time.time() - t:.0f}s)")
    videos, kept = select_candidates(con, cfg)
    p = cfg.pipeline
    print(
        f"extract: {videos:,} videos pass the gate (>= {p.min_people} people, "
        f">= {p.min_months} months, >= {p.min_own_chars} chars of own text); keeping {kept:,} mentions"
    )
    pairs = con.execute(
        "SELECT DISTINCT c.id, c.parent FROM comments c JOIN kept k ON k.comment_id = c.id"
    ).fetchall()
    t = time.time()
    store_roots(con, resolve_roots(glob, [tuple(r) for r in pairs]))
    print(f"extract: found root stories for {len(pairs):,} comments ({time.time() - t:.0f}s)")

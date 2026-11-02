"""tastetube <stage>. Each stage reads and writes work/tastetube.db, so stages re-run alone."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from tastetube import build, config, extract, judge, label, rank, store, youtube
from tastetube.llm import Runner


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def download(cfg: config.Config) -> None:
    from huggingface_hub import snapshot_download

    dest = cfg.work / "hn"
    print(f"download: open-index/hacker-news monthly Parquet files -> {dest} (about 12 GB)")
    snapshot_download(
        repo_id="open-index/hacker-news",
        repo_type="dataset",
        allow_patterns=["data/*/*.parquet"],
        local_dir=dest,
    )
    print("download: done (re-run any time; unchanged files are skipped)")


def stats(con) -> None:
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    print(f"comments with YouTube links : {q('SELECT COUNT(*) FROM comments'):>10,}")
    print(f"candidate videos            : {q('SELECT COUNT(*) FROM candidates'):>10,}")
    print(f"mentions kept for labelling : {q('SELECT COUNT(*) FROM kept'):>10,}")
    print(f"videos with metadata        : {q('SELECT COUNT(*) FROM yt WHERE available = 1'):>10,}")
    print(f"mentions labelled           : {q('SELECT COUNT(*) FROM labels'):>10,}")
    print(f"videos scored               : {q('SELECT COUNT(*) FROM scores'):>10,}")
    print(f"videos judged (all tastes)  : {q('SELECT COUNT(*) FROM judgments'):>10,}")
    print(f"open batches                : {q('SELECT COUNT(*) FROM batches'):>10,}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tastetube", description=__doc__)
    ap.add_argument("--config", help="path to taste.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download", help="download the HN archive (12 GB Parquet)")
    sub.add_parser("extract", help="find YouTube links, apply the quality gate, find story titles")
    sub.add_parser("meta", help="fetch YouTube metadata (needs YOUTUBE_API_KEY)")
    for name, helptext in (("label", "label mentions with Claude"), ("judge", "judge videos against taste.yaml")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--sync", action="store_true", help="call the API directly (fast, 2x price); for tests")
        p.add_argument("--limit", type=int, help="only the first N items; for tests")
        p.add_argument("--yes", action="store_true", help="do not ask before spending money")
    sub.add_parser("build", help="write site/data/videos.json")
    p = sub.add_parser("all", help="extract -> meta -> label -> judge -> build")
    p.add_argument("--yes", action="store_true")
    sub.add_parser("stats", help="row counts for every stage")
    args = ap.parse_args(argv)

    root = config.ROOT
    _load_dotenv(root / ".env")
    cfg = config.load(args.config)
    if args.cmd == "download":
        download(cfg)
        return 0
    con = store.connect(cfg.work)
    runner = Runner(con)
    mode = "sync" if getattr(args, "sync", False) else "batch"
    limit = getattr(args, "limit", None)
    confirm = not getattr(args, "yes", False)

    if args.cmd == "extract":
        extract.run(con, cfg)
    elif args.cmd == "meta":
        youtube.run(con, cfg.seed_ids)
    elif args.cmd == "label":
        label.run(con, cfg, runner, mode, limit, confirm)
        print(f"score: {rank.run(con):,} videos scored")
    elif args.cmd == "judge":
        rank.run(con)
        judge.run(con, cfg, runner, mode, limit, confirm)
    elif args.cmd == "build":
        rank.run(con)
        build.run(con, cfg)
    elif args.cmd == "stats":
        stats(con)
    elif args.cmd == "all":
        extract.run(con, cfg)
        youtube.run(con, cfg.seed_ids)
        label.run(con, cfg, runner, "batch", None, confirm)
        rank.run(con)
        judge.run(con, cfg, runner, "batch", None, confirm)
        build.run(con, cfg)
    return 0

"""tastetube hackertube --data DIR: build the site's data from HackerTube's open data and courses.yaml."""

from __future__ import annotations

import argparse
from pathlib import Path

from tastetube import config, hackertube


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tastetube", description=__doc__)
    ap.add_argument("--config", help="path to taste.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("hackertube", help="write site/data/videos.json from HackerTube's open data + courses.yaml")
    p.add_argument("--data", required=True, type=Path, help="unzipped hackertube-data folder")
    p.add_argument("--courses", type=Path, help="default: courses.yaml in the repository root")
    args = ap.parse_args(argv)

    cfg = config.load(args.config)
    courses = args.courses or config.ROOT / "courses.yaml"
    hackertube.run(args.data, cfg, courses, cfg.site / "data" / "videos.json")
    return 0

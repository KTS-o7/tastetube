# Notes for Claude Code

- `tastetube hackertube --data DIR` is the only stage. It reads HackerTube's `videos.jsonl` and `mentions.jsonl` (download from https://hackertube.org/data, keep it outside the repo) plus `courses.yaml`, and writes `site/data/videos.json`, which is committed.
- Every video id in `courses.yaml` must exist in HackerTube's data. Keep to videos with `hn.recommenders >= 2`.
- Do not write YouTube API data (durations, descriptions, publish dates) into `videos.json`: YouTube's terms do not allow redistributing it.
- `site/` is plain HTML, CSS and JavaScript with no build step. It reads only `site/data/videos.json`. Course items have `cr: 1` and a lecture list `ls`; they are not YouTube playlists.
- The Pages workflow replaces `?v=dev` in `site/index.html` with the commit hash. Keep the `?v=dev` suffix on asset links.
- Run `pytest -q` after every change. Tests are offline and build a tiny fixture of HackerTube data.
- Credit HackerTube and open-index/hacker-news (both ODC-By 1.0) wherever the data is shown.

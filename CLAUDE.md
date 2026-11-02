# Notes for Claude Code

- Pipeline stages share one SQLite file, `work/tastetube.db`. Each stage reads and writes it and can re-run alone.
- Never delete `llm_cache` or `batches` rows: they are paid-for answers and in-flight batches.
- DuckDB is used only in `tastetube/extract.py` for the 12 GB Parquet archive. Keep other logic in Python and SQLite so tests stay offline.
- Tests use `tests/fakes.py` instead of the Anthropic client. Run `pytest -q` after every change.
- `site/` is plain HTML, CSS and JavaScript with no build step. It reads only `site/data/videos.json` (falls back to `demo.json`).
- The judge's cache key includes the full system prompt, so any change to `taste.yaml` or the prompt re-judges every video.

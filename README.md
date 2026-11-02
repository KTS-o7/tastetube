# TasteTube

TasteTube is a personal video library. It finds the YouTube videos that Hacker News commenters kept recommending from 2007 to today, then ranks them for our taste, which is set in [`taste.yaml`](taste.yaml).

It follows the method of [HackerTube](https://hackertube.org/) by Andrej Karpathy, and adds one stage: a taste judge.

## How it works

1. **Extract.** Scan about 43 million HN comments for YouTube links. A video becomes a candidate only if at least 3 different people mention it, in at least 3 different months, each with at least 100 characters of their own words.
2. **Metadata.** Fetch title, channel, length and description from the YouTube Data API. Drop deleted and private videos.
3. **Label.** Claude Haiku labels each mention: strong recommendation, recommendation, neutral, joke or criticism. It reads up to 20 mentions per video, spread across different people.
4. **Score.** Community score = distinct months with a recommendation + 0.5 × distinct months with a strong one. Months, not comments, so one busy thread cannot inflate a video.
5. **Judge.** Claude Sonnet rates each well-loved video against `taste.yaml`: fit 0 to 3, which facets it belongs to, and one line on why we would watch it.
6. **Rank.** Taste score = fit weight × log2(1 + community score). The log squashes popularity, so a core-taste video with a real but small HN following beats a famous video that is only adjacent to our taste.
7. **Build.** Write `site/data/videos.json`. The site is static HTML, CSS and JavaScript, hosted free on GitHub Pages.

The site has two views. **Our taste** shows only videos with fit 1 or more. **All of HN** shows everything HN loves. **For you** re-ranks from the videos you like. Likes stay in your browser; there are no accounts.

## Run it

You need Python 3.11 or later, about 15 GB of free disk, an Anthropic API key and a YouTube Data API key.

```bash
git clone <this repo> && cd tastetube
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add ANTHROPIC_API_KEY and YOUTUBE_API_KEY

tastetube download            # 12 GB of monthly Parquet files from Hugging Face
tastetube extract             # YouTube links, quality gate, story titles
tastetube meta                # YouTube metadata
tastetube label --sync --limit 50 --yes   # optional: a cheap smoke test first
tastetube label               # Batch API; asks before it spends money
tastetube judge
tastetube build               # writes site/data/videos.json
python -m http.server -d site 8000        # look at it on http://localhost:8000
```

`tastetube stats` shows row counts for every stage. Every stage can re-run on its own.

To publish, commit `site/data/videos.json` and push. Then, once, open the repository's **Settings → Pages** and set **Source** to **GitHub Actions**.

### Get a YouTube API key

1. Open the [Google Cloud console](https://console.cloud.google.com/) and create a project.
2. Enable **YouTube Data API v3** for the project.
3. Create an API key under **APIs & Services → Credentials**. Restrict it to the YouTube Data API.

The free quota is 10,000 units a day. One call fetches 50 videos for 1 unit, so 10,000 candidates use about 200 units.

## Change the taste

Edit `taste.yaml`, then run `tastetube judge` and `tastetube build`. Only the judge re-runs, because labels do not depend on taste.

The best single improvement is to add `seeds`: 5 to 15 YouTube URLs we already love. Run `tastetube meta` after adding them, so the judge can read their titles.

## Cost

The CLI prints an estimate and asks before every paid step. A full first run should cost roughly USD 10 to 20, with both stages on the Batch API at half price. This is an estimate: it assumes about 100,000 labelled mentions and 7,000 judged videos. Re-runs cost almost nothing, because every answer is cached in `work/tastetube.db`.

| Stage | Model | Batch price per million tokens (input / output) |
|---|---|---|
| Label | `claude-haiku-5-5` | USD 0.05 / 0.25 |
| Judge | `claude-sonnet-5-5` | USD 1 / 5 |

Prices were checked on 2 November 2026 on the [Claude pricing page](https://platform.claude.com/docs/en/about-claude/pricing).

## Things that can go wrong

- **A batch takes a long time.** Most batches finish within an hour. The limit is 24 hours. If you stop the CLI, run the same command again; it resumes the saved batch and does not re-send it.
- **Niche gems are missing.** The 3 people, 3 months gate removes noise, and also removes rare videos. Lower `min_people` and `min_months` to 2 in `taste.yaml` for more recall.
- **The fit score is an opinion.** It comes from a model reading a short description. Add seeds, sharpen the facet text, and hide what you do not want with the `x` key.
- **The YouTube API returns 403.** The daily quota is used up, or the key is restricted to the wrong API.
- **HN escapes links.** Comment HTML stores `/` as `&#x2F;`. The extractor unescapes before it matches. Keep this in mind if you change `tastetube/links.py`.

## Data and credit

- Source: [open-index/hacker-news](https://huggingface.co/datasets/open-index/hacker-news) on Hugging Face, under the Open Data Commons Attribution License (ODC-By) 1.0. The site credits it in its footer.
- Comment excerpts on the site are short and link back to the original comment on Hacker News.
- Method: [HackerTube](https://hackertube.org/) by Andrej Karpathy.
- Code: MIT licence.

## Repository layout

```
taste.yaml           who we are, our facets, seeds, thresholds, models
tastetube/
  extract.py         DuckDB scan of the archive, quality gate, root story titles
  links.py           YouTube ID extraction and comment cleaning
  youtube.py         YouTube Data API client
  llm.py             Batch API runner with result cache and resume
  label.py           mention labels (Haiku)
  rank.py            community and taste scores
  judge.py           taste judge and video cards (Sonnet)
  build.py           site/data/videos.json
site/                static site (no build step)
tests/               pytest; runs offline with a fake Claude client
```

# TasteTube

TasteTube is a long-form watch list. It finds the lectures, talks, documentaries and whole courses that Hacker News commenters kept recommending from 2007 to today. It ranks them for our taste, set in [`taste.yaml`](taste.yaml), and tells you what each one asks of you before you commit an evening or a month.

It starts from the method of [HackerTube](https://hackertube.org/), which Claude built after a prompt from Andrej Karpathy. It differs in four ways.

| | HackerTube | TasteTube |
|---|---|---|
| What counts | Any video | Long-form only: 30 minutes or more, and whole courses |
| Unit | Single video | Single video, or a course (a YouTube playlist) with its lectures |
| Ranking | How much HN recommended it | How well it fits our taste, weighted by HN's recommendation |
| Card | Short description | Commitment card: what you come away with, what to know first, how to watch it |

## How it works

1. **Extract.** Scan about 43 million HN comments for links to YouTube videos and course playlists. An item becomes a candidate only if at least 3 different people mention it, in at least 3 different months, each with at least 100 characters of their own words.
2. **Metadata.** Fetch length, title, channel and description from the YouTube Data API. For a course, fetch every lecture and add up the hours. Drop deleted and private items.
3. **Long-form gate.** Drop anything under 30 minutes. This happens before any LLM call, so short videos cost nothing.
4. **Label.** Claude Haiku labels each mention: strong recommendation, recommendation, neutral, joke or criticism. It reads up to 20 mentions per item, spread across different people.
5. **Score.** Community score = distinct months with a recommendation + 0.5 × distinct months with a strong one. Months, not comments, so one busy thread cannot inflate an item.
6. **Judge.** Claude Sonnet rates each item against `taste.yaml` (fit 0 to 3) and writes the commitment card:
   - **You come away with:** the understanding or skill you leave with.
   - **Know first:** prerequisites beyond your level, if any.
   - **How to watch:** easy watch (relaxed, at 1.5x), focused watch (one sitting, full attention) or study session (pause, take notes, code along).
7. **Rank.** Taste score = fit weight × log2(1 + community score). The log squashes popularity, so a core-taste lecture with a small but real HN following beats a famous video that is only adjacent to our taste.
8. **Build.** Write `site/data/videos.json`. The site is static HTML, CSS and JavaScript, hosted free on GitHub Pages.

## The site

- **Our taste** shows items with fit 1 or more. **All of HN** shows everything that passed the gates.
- Filter by length: under 1 hour, 1 to 2 hours, over 2 hours, or courses.
- A course shows its lectures, tracks which ones you finished, and has a **Continue** button.
- Videos with chapters in their YouTube description show them as jump links.
- **For you** re-ranks from the items you like.
- Likes, progress and hidden items stay in your browser. There are no accounts.

## Courses from HackerTube's data (no API keys)

HackerTube publishes its labelled data: 6,454 videos with cards and 39,834 labelled HN comments, under ODC-By 1.0. The live site is built from it with one command. It needs no API key and spends nothing.

1. Download and unzip [hackertube-data.zip](https://hackertube.org/data) (17.8 MB) anywhere outside the repository.
2. Edit [`courses.yaml`](courses.yaml). Each course is an ordered list of video ids from that data, with a card: why, summary, what you come away with, what to know first, how to watch it.
3. Run the command, commit `site/data/videos.json`, and push:

```bash
tastetube hackertube --data ../hackertube-data   # writes site/data/videos.json
```

What it writes:

- **Our taste**: the courses from `courses.yaml`, in file order.
- **All of HN**: every recommended talk, lecture, course, documentary, interview and podcast in the data (about 2,300), with HackerTube's summary, why HN likes it, and up to 3 real HN quotes.

The data has no video lengths, because YouTube's terms do not allow redistributing them. So the site turns off the length filters, and "long-form" here means the video type, not its measured length.

## Run it

You need Python 3.11 or later, about 15 GB of free disk, an Anthropic API key and a YouTube Data API key.

```bash
git clone <this repo> && cd tastetube
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add ANTHROPIC_API_KEY and YOUTUBE_API_KEY

tastetube download            # 12 GB of monthly Parquet files from Hugging Face
tastetube extract             # YouTube links, quality gate, story titles
tastetube meta                # YouTube metadata, including course lectures
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

The free quota is 10,000 units a day. Each call fetches up to 50 items for 1 unit. Courses need extra calls for their lecture lists.

## Change the taste

Edit `taste.yaml`, then run `tastetube judge` and `tastetube build`. Only the judge re-runs, because labels do not depend on taste.

The best single improvement is to add `seeds`: 5 to 15 YouTube URLs you already love. Run `tastetube meta` after adding them, so the judge can read their titles.

To change what counts as long-form, edit `min_minutes` and re-run from `label`.

## Cost

The CLI prints an estimate and asks before every paid step. A full first run should cost roughly USD 5 to 15, with both stages on the Batch API at half price. This is an estimate, not a measurement: the long-form gate removes most videos before labelling, but the share it removes is not known until you run `extract` and `meta`. Re-runs cost almost nothing, because every answer is cached in `work/tastetube.db`.

| Stage | Model | Batch price per million tokens (input / output) |
|---|---|---|
| Label | `claude-haiku-5-5` | USD 0.05 / 0.25 |
| Judge | `claude-sonnet-5-5` | USD 1 / 5 |

Prices were checked on 2 November 2026 on the [Claude pricing page](https://platform.claude.com/docs/en/about-claude/pricing).

## Things that can go wrong

- **A batch takes a long time.** Most batches finish within an hour. The limit is 24 hours. If you stop the CLI, run the same command again; it resumes the saved batch and does not re-send it.
- **Great 20-minute talks are missing.** That is the long-form gate. Lower `min_minutes` if you want them.
- **Niche gems are missing.** The 3 people, 3 months gate removes noise, and also removes rare items. Lower `min_people` and `min_months` to 2 for more recall.
- **A course has fewer lectures than expected.** Deleted and private lectures are skipped, and only the first 300 lectures are read.
- **The card is an opinion.** It comes from a model reading the title, description, chapter or lecture titles and HN comments, not the video itself. Add seeds, sharpen the facet text, and hide what you do not want with the `x` key.
- **The YouTube API returns 403.** The daily quota is used up, or the key is restricted to the wrong API.
- **HN escapes links.** Comment HTML stores `/` as `&#x2F;`. The extractor unescapes before it matches. Keep this in mind if you change `tastetube/links.py`.

## Data and credit

- Source: [open-index/hacker-news](https://huggingface.co/datasets/open-index/hacker-news) on Hugging Face, under the Open Data Commons Attribution License (ODC-By) 1.0. The site credits it in its footer.
- Comment excerpts on the site are short and link back to the original comment on Hacker News.
- Courses and library: [HackerTube](https://hackertube.org/)'s open data (ODC-By 1.0). The site credits it in its banner and footer. Its labels and summaries were written by an LLM, so expect a few to be off.
- Method: [HackerTube](https://hackertube.org/).
- Code: MIT licence.

## Repository layout

```
taste.yaml           who we are, our facets, seeds, thresholds, models
tastetube/
  extract.py         DuckDB scan of the archive, quality gate, root story titles
  links.py           video, playlist and chapter parsing; comment cleaning
  youtube.py         YouTube Data API client (videos, courses, lectures)
  llm.py             Batch API runner with result cache and resume
  label.py           mention labels (Haiku)
  rank.py            community and taste scores
  judge.py           taste judge and commitment cards (Sonnet)
  build.py           site/data/videos.json
site/                static site (no build step)
tests/               pytest; runs offline with fake Claude and YouTube clients
```

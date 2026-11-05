# TasteTube

TasteTube is a long-form watch list built from the YouTube videos that Hacker News commenters kept recommending from 2007 to today. It has two parts:

- **Courses.** Ordered watch paths we picked for our taste, set in [`taste.yaml`](taste.yaml). Each one says what you come away with, what to know first and how to watch it. They live in [`courses.yaml`](courses.yaml).
- **A library.** About 2,300 talks, lectures, documentaries, interviews and podcasts that HN recommended, each with a summary, why HN likes it, and real HN quotes.

Live site: <https://shenthar.me/tastetube/>

The data comes from [HackerTube](https://hackertube.org/), which publishes its labelled Hacker News data for reuse. HackerTube was built by Claude after a prompt from Andrej Karpathy. TasteTube adds the courses, the long-form focus and the per-course cards.

## The site

- **Our taste** shows the courses, in `courses.yaml` order. A course plays lecture by lecture, tracks which ones you finished, and has a **Continue** button. Press `n` to mark a lecture done and play the next one.
- **All of HN** shows the library, grouped by HackerTube's 16 topic areas.
- **For you** re-ranks from the items you like.
- Likes, progress and hidden items stay in your browser. There are no accounts.
- The site is static HTML, CSS and JavaScript with no build step, hosted on GitHub Pages.

## Build the data

You need Python 3.11 or later. No API key is needed, and nothing costs money.

```bash
git clone https://github.com/KTS-o7/tastetube && cd tastetube
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Download and unzip https://hackertube.org/data (17.8 MB) outside the repository, then:
tastetube hackertube --data ../hackertube-data   # writes site/data/videos.json
python -m http.server -d site 8000               # look at it on http://localhost:8000
```

To publish, commit `site/data/videos.json` and push to `main`. The Pages workflow deploys `site/`. It replaces `?v=dev` in `index.html` with the commit hash, so browsers never pair an old `app.js` with new data.

## Add or change a course

Edit `courses.yaml`. Each course has an id, a title, the `taste.yaml` facets it belongs to, a watch mode (`easy`, `focused` or `study`), a card (why, summary, takeaway, prerequisites), and an ordered list of YouTube video ids. Every id must be in HackerTube's `videos.jsonl`; the command stops with the missing ids if one is not.

To find candidates, search `videos.jsonl` for a topic and keep videos with `hn.recommenders` of 2 or more. The current courses use only those.

## What the library includes

A video is in the library if HN recommended it at least once, it is not news, and its type is talk, lecture, course, documentary, interview or podcast. Every video used in a course is also included.

The data has no video lengths, because YouTube's terms do not allow redistributing them. So "long-form" means the video type, not a measured length, and the site turns off the length filters. Adding lengths needs a YouTube Data API key and is not done yet.

## Data and credit

- Videos, summaries, topics and labelled comments: [HackerTube](https://hackertube.org/data)'s open data, under the Open Data Commons Attribution License (ODC-By) 1.0. Its labels and summaries were written by an LLM, so expect a few to be off.
- Hacker News comments: the [open-index/hacker-news](https://huggingface.co/datasets/open-index/hacker-news) dataset (ODC-By 1.0). Comments remain the work of their authors. Quotes on the site are short and link back to the comment on Hacker News.
- The site credits both in its banner and footer. It is not affiliated with YouTube, Hacker News or Y Combinator.
- Code: MIT licence.

## Repository layout

```
courses.yaml          our courses: cards and ordered video ids
taste.yaml            who we are and the facets courses are filed under
tastetube/
  hackertube.py       HackerTube data + courses.yaml -> site/data/videos.json
  config.py           loads taste.yaml
  cli.py              tastetube hackertube --data DIR
site/                 static site; reads only site/data/videos.json
tests/                pytest, offline
```

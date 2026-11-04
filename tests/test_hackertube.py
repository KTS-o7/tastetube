"""HackerTube open data + courses.yaml -> the site's videos.json shape."""

import json

import pytest

from tastetube import config, hackertube


def video(vid, kind="talk", recommenders=3, shelf="evergreen", score=4.0):
    return {
        "vid": vid, "title": f"Title {vid}", "channel": "Chan", "summary": "S", "why_hn": "W",
        "content_type": kind, "shelf_life": shelf, "score": score,
        "categories": [{"id": "x", "name": "X", "area": "a", "area_name": "Area"}],
        "hn": {"recommenders": recommenders, "rec_months": 2, "first_year": 2019, "last_year": 2021},
    }


def mention(cid, vid, stance="rec", month="2020-01", author="a"):
    return {"hn_comment_id": cid, "vid": vid, "author": author, "month": month, "story_title": "Story",
            "stance": stance, "quote": "", "text": f"Watch [VIDEO] now ({cid})"}


@pytest.fixture
def data(tmp_path):
    vids = [
        video("AAAAAAAAAAA"), video("BBBBBBBBBBB", kind="lecture"),
        video("shortclip01", kind="explainer"),        # not a long-form type, only kept because a course uses it
        video("newsnews001", shelf="news"),            # dropped: news
        video("citedonly01", recommenders=0),          # dropped: never recommended
    ]
    ments = [mention(1, "AAAAAAAAAAA", "strong_rec", "2019-05", "x"), mention(2, "BBBBBBBBBBB", "rec", "2021-02", "y"),
             mention(3, "shortclip01", "rec", "2020-07", "z"), mention(4, "AAAAAAAAAAA", "joke")]
    (tmp_path / "videos.jsonl").write_text("\n".join(json.dumps(v) for v in vids))
    (tmp_path / "mentions.jsonl").write_text("\n".join(json.dumps(m) for m in ments))
    return tmp_path


def course(**kw):
    c = dict(id="c1", title="Course", facets=["systems"], mode="study", why="w", summary="s",
             takeaway="t", prereqs="p", videos=["shortclip01", "AAAAAAAAAAA"])
    c.update(kw)
    return hackertube.Course(**c)


def test_courses_and_library(data):
    out = hackertube.collect(data, [course()], config.load())
    items = {v["id"]: v for v in out["videos"]}

    c = out["videos"][0]
    assert c["id"] == "tt-c1" and c["cr"] == 1 and c["cu"] == 1 and c["f"] == 3
    assert [lec["id"] for lec in c["ls"]] == ["shortclip01", "AAAAAAAAAAA"]  # courses.yaml order
    assert c["th"] == "shortclip01" and c["yr"] == [2019, 2020] and c["n"] == 2
    assert "[VIDEO]" not in json.dumps(out)

    assert set(items) == {"tt-c1", "AAAAAAAAAAA", "BBBBBBBBBBB", "shortclip01"}
    assert items["AAAAAAAAAAA"]["m"][0]["c"] == 1  # strong recommendation first, joke never quoted
    assert len(items["AAAAAAAAAAA"]["m"]) == 1
    assert out["meta"]["durations"] is False and out["meta"]["counts"]["ours"] == 1


def test_unknown_video_is_an_error(data):
    with pytest.raises(ValueError, match="not in HackerTube data"):
        hackertube.collect(data, [course(videos=["AAAAAAAAAAA", "ZZZZZZZZZZZ"])], config.load())


def test_committed_courses_file_is_valid():
    cfg = config.load()
    courses = hackertube.load_courses(config.ROOT / "courses.yaml", {f.id for f in cfg.facets})
    assert courses and all(len(c.videos) >= 5 for c in courses)

"""End-to-end run on a tiny synthetic HN, with fake Claude and fake YouTube.

The DuckDB scan and parent walk need the real archive, so here we feed rows
straight into `ingest` and set story titles with `store_roots`.
"""

import json
from datetime import datetime, timezone

import pytest

from fakes import FakeClient
from tastetube import build, config, extract, judge, label, rank, store
from tastetube.llm import Job, Runner, make_key
from tastetube.rank import community_score, taste_score

PAD = " I keep coming back to it because it explains the core idea from first principles and the pacing is great."


def ts(y, m):
    return int(datetime(y, m, 15, tzinfo=timezone.utc).timestamp())


def link(vid):
    return f'<a href="https:&#x2F;&#x2F;www.youtube.com&#x2F;watch?v={vid}" rel="nofollow">x</a>'


GPT, RAFT, RICK, FEW, SHORT = "kCc8FmEb1nY", "RAFTtalk_01", "dQw4w9WgXcQ", "fewPeople01", "shortText01"

ROWS = [
    # GPT lecture: 4 people over 4 months; alice twice.
    (1, "alice", ts(2020, 1), 100, "Must watch. " + link(GPT) + PAD),
    (2, "bob", ts(2021, 3), 101, "Great transformer lecture " + link(GPT) + PAD),
    (3, "carol", ts(2022, 5), 3001, "Builds GPT from scratch " + link(GPT) + PAD),
    (4, "dave", ts(2023, 7), 102, link(GPT) + PAD),
    (5, "alice", ts(2023, 8), 103, "Again: " + link(GPT) + PAD),
    # Raft talk: 3 people over 3 months, also linked alongside the GPT video once.
    (6, "erin", ts(2019, 2), 104, "Raft explained well " + link(RAFT) + PAD),
    (7, "frank", ts(2020, 6), 105, "Raft talk " + link(RAFT) + " and " + link(GPT) + PAD),
    (8, "grace", ts(2021, 9), 106, "Raft " + link(RAFT) + PAD),
    # Rickroll: passes the gate, but every mention is a joke.
    (9, "h1", ts(2018, 1), 107, "Obligatory " + link(RICK) + PAD),
    (10, "h2", ts(2019, 1), 108, "Obligatory " + link(RICK) + PAD),
    (11, "h3", ts(2020, 1), 109, "Obligatory " + link(RICK) + PAD),
    # Only two people: fails the gate.
    (12, "i1", ts(2018, 1), 110, link(FEW) + PAD),
    (13, "i2", ts(2019, 1), 111, link(FEW) + PAD),
    # Three people but almost no own text: fails the gate.
    (14, "j1", ts(2018, 1), 112, "see " + link(SHORT)),
    (15, "j2", ts(2019, 1), 113, "see " + link(SHORT)),
    (16, "j3", ts(2020, 1), 114, "see " + link(SHORT)),
    # No YouTube ID at all (channel link): ignored.
    (17, "k", ts(2020, 1), 115, "https://www.youtube.com/@somechannel" + PAD),
]

YT = {
    GPT: ("Let's build GPT: from scratch, in code, spelled out.", "Andrej Karpathy"),
    RAFT: ("Raft: understandable distributed consensus", "Some Conf"),
    RICK: ("Never Gonna Give You Up", "Rick Astley"),
}


@pytest.fixture
def env(tmp_path):
    cfg = config.load()
    cfg.work = tmp_path / "work"
    cfg.site = tmp_path / "site"
    cfg.pipeline.mentions_per_video = 4
    con = store.connect(cfg.work)
    return cfg, con


def seed(con, cfg):
    assert extract.ingest(con, ROWS) == 16
    videos, kept = extract.select_candidates(con, cfg)
    extract.store_roots(con, {cid: (900 + cid, f"Story {cid}") for cid in range(1, 17)})
    for vid, (title, ch) in YT.items():
        con.execute("INSERT INTO yt VALUES (?,1,?,?,'2023-02-01T00:00:00Z','desc',7000,1,10,0)", (vid, title, ch))
    con.commit()
    return videos, kept


def test_gate_and_sampling(env):
    cfg, con = env
    videos, kept = seed(con, cfg)
    cands = {r[0]: (r[1], r[2]) for r in con.execute("SELECT video_id, people, months FROM candidates")}
    assert set(cands) == {GPT, RAFT, RICK}
    assert cands[GPT] == (5, 6)  # alice, bob, carol, dave, frank; alice twice
    # GPT is capped at 4 kept mentions, and alice's second comment (5) is dropped first.
    gpt = [r[0] for r in con.execute("SELECT comment_id FROM kept WHERE video_id = ? ORDER BY 1", (GPT,))]
    assert len(gpt) == 4 and 5 not in gpt


def test_end_to_end(env):
    cfg, con = env
    seed(con, cfg)
    client = FakeClient()
    runner = Runner(con, client=client, poll_seconds=0)

    label.run(con, cfg, runner, confirm=False)
    labels = dict(((r[0], r[1]), r[2]) for r in con.execute("SELECT comment_id, video_id, label FROM labels"))
    assert labels[(1, GPT)] == "strong_recommendation"
    assert labels[(9, RICK)] == "joke"
    assert rank.run(con) == 3

    judge.run(con, cfg, runner, confirm=False)
    fits = dict(con.execute("SELECT video_id, fit FROM judgments"))
    assert fits == {GPT: 3, RAFT: 2}  # the rickroll scores 0 on HN, so it is never judged

    out = build.run(con, cfg)
    data = json.loads(out.read_text())
    ids = [v["id"] for v in data["videos"]]
    assert ids == [GPT, RAFT]
    top = data["videos"][0]
    assert top["f"] == 3 and top["fa"] == ["llm-systems", "ml-first-principles"]
    assert top["m"][0]["a"] == "alice" and len(top["m"]) == 3
    assert "youtube" not in top["m"][0]["x"].lower()
    assert top["hy"] == [2020, 2023]
    assert data["meta"]["counts"]["ours"] == 2

    # Re-running pays nothing: every answer comes from the cache.
    created = client.messages.batches.created
    label.run(con, cfg, runner, confirm=False)
    judge.run(con, cfg, runner, confirm=False)
    assert client.messages.batches.created == created

    # Editing the taste re-runs the judge only.
    cfg.who += " Also likes Raft."
    judge.run(con, cfg, runner, confirm=False)
    assert client.messages.batches.created == created + 1


def test_resume_after_crash(env):
    cfg, con = env
    client = FakeClient()
    runner = Runner(con, client=client, poll_seconds=0)
    schema = label.SCHEMA
    jobs = [Job(make_key("label", "m", label.SYSTEM, u), u) for u in ("Comment: must watch", "Comment: ok")]
    # Simulate a run that sent a batch and then died before reading results.
    params = [{"custom_id": j.key, "params": {
        "system": [{"text": label.SYSTEM}], "messages": [{"content": j.user}],
        "output_config": {"format": {"schema": schema}}}} for j in jobs]
    b = client.messages.batches.create(requests=params)
    con.execute("INSERT INTO batches VALUES (?, 'label', 2, 0)", (b.id,))
    out = runner.run("label", "m", label.SYSTEM, jobs, schema, 32, confirm=False)
    assert client.messages.batches.created == 1  # resumed, did not re-send
    assert out[jobs[0].key] == {"label": "strong_recommendation"}
    assert con.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0


def test_sync_mode_and_limit(env):
    cfg, con = env
    seed(con, cfg)
    client = FakeClient()
    label.run(con, cfg, Runner(con, client=client), mode="sync", limit=2, confirm=False)
    assert client.messages.sync_calls == 2
    assert con.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 2


def test_scores():
    # HackerTube's example: recommended in 4 months, strongly in 2 of them -> 5.
    m = [("2020-01", "strong_recommendation"), ("2020-01", "recommendation"),
         ("2021-01", "strong_recommendation"), ("2022-01", "recommendation"),
         ("2023-01", "recommendation"), ("2024-01", "joke"), ("2024-02", "neutral")]
    assert community_score(m) == (5.0, 4, 2)
    w = {1: 1.0, 2: 2.0, 3: 3.0}
    assert taste_score(7, 3, w) == 9.0
    assert taste_score(100, 0, w) == 0.0
    assert taste_score(3, 3, w) > taste_score(31, 1, w)  # taste beats raw popularity


def test_config_seeds_and_hash(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text(
        "taste:\n  who: me\n  facets: [{id: a, name: A, about: x}]\n"
        "  seeds: ['https://youtu.be/kCc8FmEb1nY', 'aircAruvnKk', 'not a url']\n"
    )
    cfg = config.load(p)
    assert cfg.seed_ids == ["kCc8FmEb1nY", "aircAruvnKk"]
    h = cfg.taste_hash()
    cfg.avoid.append("x")
    assert cfg.taste_hash() != h

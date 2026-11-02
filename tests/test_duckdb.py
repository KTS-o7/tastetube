"""The two DuckDB steps, on a five-row Parquet file shaped like open-index/hacker-news."""

import pytest

duckdb = pytest.importorskip("duckdb")

from tastetube import extract  # noqa: E402


def test_scan_and_roots(tmp_path):
    d = tmp_path / "hn" / "data" / "2020"
    d.mkdir(parents=True)
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE t AS SELECT * FROM (VALUES
          (1::UINTEGER, 0::UTINYINT, 1::TINYINT, 'op', TIMESTAMPTZ '2020-01-01 00:00:00+00',
           NULL::VARCHAR, 0::UTINYINT, NULL::UINTEGER, 'Story one'),
          (2, 0, 2, 'a', TIMESTAMPTZ '2020-01-02 00:00:00+00', 'see youtu.be&#x2F;kCc8FmEb1nY', 0, 1, NULL),
          (3, 0, 2, 'b', TIMESTAMPTZ '2020-01-03 00:00:00+00',
           'https:&#x2F;&#x2F;www.youtube.com&#x2F;watch?v=aircAruvnKk', 0, 2, NULL),
          (4, 1, 2, 'c', TIMESTAMPTZ '2020-01-04 00:00:00+00', 'deleted youtu.be/aircAruvnKk', 0, 1, NULL),
          (5, 0, 2, 'd', TIMESTAMPTZ '2020-01-05 00:00:00+00', 'no link here', 0, 1, NULL)
        ) v("id", "deleted", "type", "by", "time", "text", "dead", "parent", "title")
        """
    )
    con.execute(f"COPY t TO '{d / '2020-01.parquet'}' (FORMAT parquet)")
    glob = str(tmp_path / "hn" / "data" / "*" / "*.parquet")

    rows = list(extract.scan_youtube_comments(glob))
    assert sorted(r[0] for r in rows) == [2, 3]
    assert {r[0]: r[2] for r in rows}[2] == 1577923200  # 2020-01-02 UTC

    roots = extract.resolve_roots(glob, [(2, 1), (3, 2)])
    assert roots == {2: (1, "Story one"), 3: (1, "Story one")}

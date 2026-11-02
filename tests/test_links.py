from tastetube.links import clean_text, excerpt, extract_ids, extract_playlists, is_course, own_text, parse_chapters

PL = "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"


def test_playlists():
    assert extract_playlists(f"https:&#x2F;&#x2F;www.youtube.com&#x2F;playlist?list={PL}") == [PL]
    assert extract_playlists(f"youtube.com/watch?v=kCc8FmEb1nY&amp;list={PL}&amp;index=2") == [PL]
    assert extract_playlists("youtube.com/watch?v=kCc8FmEb1nY&list=RDkCc8FmEb1nY") == []  # a mix, not a course
    assert extract_playlists(f"example.com/?list={PL}") == []
    assert is_course(PL) and not is_course("kCc8FmEb1nY")


def test_chapters():
    desc = "Intro text\n0:00 Intro\n(05:10) The problem\n1:02:03 - Wrap up\nnot 9:99 a chapter"
    assert parse_chapters(desc) == [(0, "Intro"), (310, "The problem"), (3723, "Wrap up")]
    assert parse_chapters("1:00 a\n2:00 b\n3:00 c") == []  # YouTube requires the first at 0:00
    assert parse_chapters("0:00 a\n2:00 b") == []  # and at least 3

# Real HN storage format: '/' is escaped as &#x2F; and '&' as &amp; inside links.
HN = (
    'Best intro I know:<p><a href="https:&#x2F;&#x2F;www.youtube.com&#x2F;watch?v=kCc8FmEb1nY" '
    'rel="nofollow">https:&#x2F;&#x2F;www.youtube.com&#x2F;watch?v=kCc8FmEb1nY</a><p>'
    'Also <a href="https:&#x2F;&#x2F;youtu.be&#x2F;VMj-3S1tku0?t=120" rel="nofollow">this</a>'
)


def test_ids_from_escaped_html():
    assert extract_ids(HN) == ["kCc8FmEb1nY", "VMj-3S1tku0"]


def test_id_forms():
    cases = {
        "https://m.youtube.com/watch?feature=share&amp;v=aircAruvnKk": "aircAruvnKk",
        "https://www.youtube.com/embed/aircAruvnKk?rel=0": "aircAruvnKk",
        "https://www.youtube-nocookie.com/embed/aircAruvnKk": "aircAruvnKk",
        "https://youtube.com/shorts/aircAruvnKk": "aircAruvnKk",
        "https://www.youtube.com/live/aircAruvnKk?si=x": "aircAruvnKk",
        "old style comment www.youtube.com/watch?v=aircAruvnKk#t=30": "aircAruvnKk",
    }
    for text, vid in cases.items():
        assert extract_ids(text) == [vid], text


def test_no_false_ids():
    for text in (
        "https://www.youtube.com/@3blue1brown",
        "https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=aircAruvnKkTOOLONG",
        None,
        "",
    ):
        assert extract_ids(text) == [], text


def test_dedup_keeps_order():
    t = "youtu.be/aircAruvnKk youtu.be/kCc8FmEb1nY youtube.com/watch?v=aircAruvnKk"
    assert extract_ids(t) == ["aircAruvnKk", "kCc8FmEb1nY"]


def test_clean_and_own_text():
    assert "https://www.youtube.com/watch?v=kCc8FmEb1nY" in clean_text(HN)
    assert own_text(HN) == "Best intro I know: Also"


def test_excerpt():
    assert excerpt("a b c", 10) == "a b c"
    out = excerpt("word " * 100, 30)
    assert out.endswith("…") and len(out) <= 31

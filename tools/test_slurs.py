"""붙임줄이 아닌 곡선은 슬러로 싣는다 — 여러 음표를 건너뛴다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detstruct import _slurs, _ties                            # noqa: E402

SP = 10.0


def head(x, y=50.0):
    return {"x": x, "y": y, "w": 10.0, "h": 8.0}


def curve(x0, x1, y=30.0):
    return {"x": x0, "y": y, "w": x1 - x0, "h": 12.0}


def test_long_arc_spans_many_notes():
    hs = [head(100), head(140, 60), head(180, 40), head(220, 55), head(300)]
    # 처음 네 음표를 덮는 긴 아치
    out = _slurs(hs, [curve(100, 232)], SP, set())
    assert out == [(0, 3)], out


def test_short_blob_is_not_a_slur():
    hs = [head(100), head(140)]
    assert _slurs(hs, [curve(100, 108)], SP, set()) == []


def test_tie_pair_is_not_drawn_twice():
    # 같은 높이 이웃 둘 = 붙임줄. 이미 그려지므로 슬러로 또 싣지 않는다.
    hs = [head(100), head(140)]
    c = [curve(102, 148)]
    assert _ties(hs, c, SP) == {0}
    assert _slurs(hs, c, SP, {0}) == []


def test_overlapping_slurs_keep_one():
    hs = [head(100), head(140), head(180), head(220)]
    out = _slurs(hs, [curve(100, 192), curve(140, 232)], SP, set())
    assert len(out) == 1, out
    assert out[0] == (0, 2), out       # 먼저 시작하고 더 긴 쪽


def test_starts_and_stops_balance():
    hs = [head(100 + 40 * i) for i in range(8)]
    out = _slurs(hs, [curve(100, 192), curve(260, 352)], SP, set())
    starts = [a for a, _ in out]
    stops = [b for _, b in out]
    assert len(starts) == len(stops) == len(set(starts)) == len(set(stops))
    assert all(a < b for a, b in out)


if __name__ == "__main__":
    test_long_arc_spans_many_notes()
    test_short_blob_is_not_a_slur()
    test_tie_pair_is_not_drawn_twice()
    test_overlapping_slurs_keep_one()
    test_starts_and_stops_balance()
    print("ok")

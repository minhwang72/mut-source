"""붙임점은 빔 묶음이 8분 단위로 끝나게 붙인다 — 못 가르면 짐작으로 표시한다."""
import sys
sys.path.insert(0, "tools")
from fitdur import promote_dots


def n(d, g, sc, x):
    return {"duration": d, "dotted": False, "beamGroup": g, "dotScore": sc, "x": x}


def test_dot_goes_where_the_beam_group_needs_it():
    # 실측 day2conti-2 단1 마디1 — 점수만 보면 8분 둘(0.494·0.485)에 붙는다
    ns = [n("eighth", 0, .463, 0), n("16th", 0, .319, 1), n("eighth", 1, .485, 2),
          n("eighth", 1, .494, 3), n("eighth", 2, .487, 4), n("16th", 2, .389, 5),
          n("eighth", -1, .445, 6)]
    m = {"notes": ns, "rest": 0.5, "items": list(ns)}
    promote_dots([[m]])
    assert [x["dotted"] for x in ns] == [True, False, False, False, True, False, False]
    assert not any(x.get("guessed") for x in ns)


def test_close_scores_without_groups_are_a_guess():
    # 빔 없는 4분 넷 중 하나에 점 — 점수 차가 0.05 미만이면 찍은 것이다
    ns = [n("quarter", -1, .45, 0), n("quarter", -1, .46, 1), n("quarter", -1, .44, 2)]
    m = {"notes": ns, "rest": 0.5, "items": list(ns)}
    promote_dots([[m]])
    assert sum(x["dotted"] for x in ns) == 1
    assert any(x.get("guessed") for x in ns)


if __name__ == "__main__":
    test_dot_goes_where_the_beam_group_needs_it()
    test_close_scores_without_groups_are_a_guess()
    print("ok")


def test_twin_beam_label_is_dropped():
    from durations import _drop_twin_beams
    b1 = {"class": "beam1", "x": 267, "y": 1249, "w": 55, "h": 19, "conf": 0.47}
    ghost = {"class": "beam2", "x": 267, "y": 1247, "w": 58, "h": 23, "conf": 0.38}
    stub = {"class": "beam2", "x": 320, "y": 1246, "w": 25, "h": 26, "conf": 0.89}
    real = {"class": "beam2", "x": 270, "y": 1249, "w": 50, "h": 20, "conf": 0.90}
    assert _drop_twin_beams([b1, ghost, stub], 17.75) == [b1, stub]
    assert _drop_twin_beams([b1, real], 17.75) == [b1, real]     # 더 확신하면 남긴다


if __name__ == "__main__":
    test_twin_beam_label_is_dropped()
    print("ok twin")


def test_dot_moves_to_the_group_that_needs_it():
    from fitdur import regroup_dots
    # 실측 day2sb-1 단3 마디1: [8,16] [8,8.] [8.,16] — 점 하나가 옆 묶음에 붙었다
    ns = [n("eighth", 0, .472, 0), n("16th", 0, .536, 1), n("eighth", 1, .545, 2),
          n("eighth", 1, .552, 3), n("eighth", 2, .558, 4), n("16th", 2, .439, 5)]
    ns[3]["dotted"] = ns[4]["dotted"] = True
    m = {"notes": ns, "rest": 1.0, "items": list(ns)}
    assert regroup_dots([[m]]) == 1
    assert [x["dotted"] for x in ns] == [True, False, False, False, True, False]
    assert not any(x.get("guessed") for x in ns)


if __name__ == "__main__":
    test_dot_moves_to_the_group_that_needs_it()
    print("ok move")

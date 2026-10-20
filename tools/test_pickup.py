"""못갖춘마디 짝 — 첫 마디 + 끝 마디 = 한 마디일 때만 인정하고 잠근다."""
import sys
sys.path.insert(0, "tools")
from fitdur import pickup_pair, fit_page


def m(*durs):
    return {"notes": [{"duration": d, "dotted": False, "x": i} for i, d in enumerate(durs)],
            "rest": 0.0, "items": []}


def test_pair_is_locked_and_kept():
    sysA = [m("quarter"), m("half", "half")]
    sysB = [m("half", "half"), m("half", "eighth", "eighth")]   # 끝 마디 3박
    pages = [sysA, sysB]
    assert pickup_pair(pages) == {(0, 0), (1, 1)}
    fit_page(pages)
    assert [n["duration"] for n in sysB[1]["notes"]] == ["half", "eighth", "eighth"]


def test_lone_short_last_measure_is_not_a_pickup():
    pages = [[m("half", "half"), m("half", "eighth", "eighth")]]  # 첫 마디는 온전
    assert pickup_pair(pages) == set()


if __name__ == "__main__":
    test_pair_is_locked_and_kept()
    test_lone_short_last_measure_is_not_a_pickup()
    print("ok")

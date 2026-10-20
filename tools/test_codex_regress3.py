"""Codex 3차 리뷰(빔 묶음·붙임점) 재현 8건 — 합성 입력만 쓴다.

    python tools/test_codex_regress3.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from fitdur import promote_dots, regroup_dots                 # noqa: E402
from durations import _drop_twin_beams, beam_runs              # noqa: E402
from local_reader import broken_beam_groups                   # noqa: E402


def note(d, g=-1, sc=0.0, x=0, dotted=False, rest=False, chord=False, measure=1):
    return {"duration": d, "dotted": dotted, "beamGroup": g, "dotScore": sc, "x": x,
            "rest": rest, "chord": chord, "measure": measure}


def struct(*ns):
    return {"systems": [{"notes": list(ns)}]}


def test_rest_led_sixteenths_are_fine():                      # ①
    st = struct(note("16th", rest=True), note("16th", 0), note("16th", 0),
                note("16th", 0), note("quarter"), note("quarter"), note("quarter"))
    assert broken_beam_groups(st) == 0
    st = struct(note("eighth", 0), note("16th", rest=True), note("16th", 0),
                note("half"), note("quarter"))
    assert broken_beam_groups(st) == 0


def test_misplaced_dot_is_still_caught():
    # day2 오답: [8,16] [8,8.] — 첫 묶음이 0.75박에서 끝난다
    wrong = struct(note("eighth", 0), note("16th", 0), note("eighth", 1),
                   note("eighth", 1, dotted=True), note("half"))
    right = struct(note("eighth", 0, dotted=True), note("16th", 0), note("eighth", 1),
                   note("eighth", 1), note("half"))
    assert broken_beam_groups(wrong) == 1
    assert broken_beam_groups(right) == 0


def m_of(ns, rest=0.0):
    for i, x in enumerate(ns):
        x["x"] = i
    return {"notes": [x for x in ns if not x["rest"]], "rest": rest, "items": list(ns)}


def test_strong_dot_is_not_moved():                           # ②
    ns = [note("eighth", 0, 0.0), note("16th", rest=True), note("16th", 0),
          note("eighth", -1, .8, dotted=True), note("16th"), note("half")]
    m = m_of(ns, rest=0.25)
    assert regroup_dots([[m]]) == 0
    assert ns[3]["dotted"] and not ns[0]["dotted"]


def test_receiver_needs_ink():
    ns = [note("eighth", 0, 0.1), note("16th", 0), note("eighth", 1, .5),
          note("eighth", 1, .55, dotted=True), note("half")]
    m = m_of(ns)
    assert regroup_dots([[m]]) == 0          # 받을 8분의 잉크가 0.1


def test_cross_bar_beam_fragment_is_left_alone():             # ③
    ns = [note("half"), note("eighth"), note("eighth", -1, .5, dotted=True),
          note("eighth", 0, .5), note("16th", 0)]
    m = m_of(ns)                             # 빔 조각이 마디 끝(4박)에서 끝난다
    assert regroup_dots([[m]]) == 0


def test_beam_rule_overriding_ink_is_a_guess():               # ④
    # 빔 밖 8분 .54 · 빔 안 8분 .40 — 묶음은 안쪽을, 잉크는 바깥쪽을 원한다
    ns = [note("eighth", 0, .40), note("16th", 0), note("eighth", -1, .54),
          note("eighth"), note("half")]
    m = m_of(ns)
    promote_dots([[m]])
    assert any(x.get("guessed") for x in ns)


def test_slanted_real_double_beam_is_kept():                  # ⑤
    b1 = {"class": "beam1", "x": 100, "y": 50, "w": 80, "h": 20, "conf": .95}
    b2 = {"class": "beam2", "x": 100, "y": 57.5, "w": 80, "h": 20, "conf": .90}
    assert _drop_twin_beams([b1, b2], 10.0) == [b1, b2]


def test_separate_beams_six_tenths_apart_stay_apart():       # ⑥
    a = {"class": "beam1", "x": 100, "y": 50, "w": 30, "h": 5}
    b = {"class": "beam1", "x": 136, "y": 50, "w": 30, "h": 5}
    assert len(beam_runs([a, b], 10.0)) == 2


def test_chord_member_follows_moved_dot():                    # ⑦
    ns = [note("eighth", 0, .47), note("eighth", 0, chord=True), note("16th", 0),
          note("eighth", 1, .5), note("eighth", 1, .55, dotted=True), note("half")]
    m = m_of(ns)
    assert regroup_dots([[m]]) == 1
    assert ns[0]["dotted"] and ns[1]["dotted"]


def test_none_beam_group_does_not_crash():                    # ⑧
    st = struct(dict(note("whole", rest=True), beamGroup=None))
    assert broken_beam_groups(st) == 0


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:                                # noqa: BLE001
            failed += 1
            print("FAIL", t.__name__, type(e).__name__, e)
    print(f"{len(tests) - failed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)

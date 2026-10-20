"""
넘치는 마디에서 화소로 찍은 붙임점을 거둔다 (`promote_dots` 의 거울상).

실측 근거(day2sb-1 단5 마디2): 길고 납작한 이음줄이 붙임점 자리를 지나
점수 0.565 짜리 가짜 점이 생겼다. 2분음표가 점2분음표가 되자 마디가 5박,
fit_page 가 **멀쩡한 4분음표 두 개를 8분음표로 비틀어** 4박을 맞췄다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fitdur import demote_dots, promote_dots                   # noqa: E402


def note(d, dotted=False, score=0.5):
    return {"duration": d, "dotted": dotted, "dotScore": score}


def measure(notes, rest=0.0):
    return {"notes": notes, "rest": rest, "items": list(notes)}


def test_demotes_the_dot_that_makes_it_fit():
    # ♩ ♩ 𝅗𝅥.  = 5박 → 점을 거두면 정확히 4박
    ms = [measure([note("quarter"), note("quarter"),
                   note("half", True, 0.565)]),
          measure([note("whole")])]
    assert demote_dots([ms]) == 1
    assert ms[0]["notes"][2]["dotted"] is False
    assert ms[0]["notes"][2]["dotDemoted"] is True


def test_leaves_a_measure_that_already_fits():
    ms = [measure([note("quarter"), note("quarter"), note("half")]),
          measure([note("whole")])]
    assert demote_dots([ms]) == 0


def test_keeps_a_dot_the_detector_saw_as_a_box():
    # dotScore 1.0 = 검출기가 상자로 봤다 — 화소 점수와 독립된 증거다
    ms = [measure([note("quarter"), note("quarter"),
                   note("half", True, 1.0)]),
          measure([note("whole")])]
    assert demote_dots([ms]) == 0


def test_does_not_undo_what_promote_just_did():
    # 모자란 마디 → 승격. 그 뒤 거울상을 돌려도 되돌리지 않는다.
    # ♩ ♩ ♩ ♪ = 3.5박 → 4분음표에 점을 붙이면 정확히 4박
    ms = [measure([note("quarter", False, 0.0), note("quarter", False, 0.0),
                   note("quarter", False, 0.50), note("eighth", False, 0.0)]),
          measure([note("whole")])]
    assert promote_dots([ms]) == 1
    assert ms[0]["notes"][2]["dotted"] is True    # 점수가 가장 높은 음표
    assert demote_dots([ms]) == 0                 # 다시 거두지 않는다
    assert ms[0]["notes"][2]["dotted"] is True


if __name__ == "__main__":
    test_demotes_the_dot_that_makes_it_fit()
    test_leaves_a_measure_that_already_fits()
    test_keeps_a_dot_the_detector_saw_as_a_box()
    test_does_not_undo_what_promote_just_did()
    print("ok")
